"""Тесты переноса данных из старого проекта.

Перенос делается один раз и на боевых данных, поэтому проверяется в том
числе поведение на мусоре: старый файл пользователей достраивался по ходу
и записи разных лет выглядят по-разному.
"""

import datetime as dt
import json
from pathlib import Path

import pytest

from app.db.import_legacy import LegacyImporter, user_from_legacy
from app.domain.models import LoginType, Student, normalize


LEGACY_USER = {
    "login": "ivan",
    "password": "secret",
    "netschool_url": "https://sgo.example.ru",
    "netschool_school": "МОУ СОШ №1",
    "login_type": "esia",
    "enabled": True,
    "check_interval": 600,
    "filters": {"exclude": ["Ответ на уроке", "Домашнее задание"]},
    "subject_filters": {"include": ["Алгебра"]},
    "quiet_hours": {"start": "22:00", "end": "07:00"},
    "weekly_summary_enabled": True,
    "display_name": "Иван",
    "student_name": "Иванов Иван",
    "selected_student_id": 10,
    "available_students": [{"id": 10, "name": "Иванов Иван"}, {"id": 11, "name": "Иванова А."}],
    "notify_changes": False,
    "notify_deletes": True,
    "notify_mail": True,
    "notify_homework": False,
    "mail_seen_ids": [101, 102, 103],
}


@pytest.fixture
def legacy_dir(tmp_path: Path) -> Path:
    root = tmp_path / "forwarder_data"
    (root / "netschool_users").mkdir(parents=True)
    (root / "netschool_sessions").mkdir(parents=True)
    (root / "netschool_users" / "netschool_users.json").write_text(
        json.dumps({"users": {"1": LEGACY_USER}}, ensure_ascii=False), encoding="utf-8"
    )
    return root


@pytest.fixture
def importer(legacy_dir, users, marks, sessions, miniapp):
    return LegacyImporter(
        legacy_dir, users=users, state=marks, sessions=sessions, miniapp=miniapp
    )


class TestUserConversion:
    def test_all_fields_are_carried_over(self):
        user = user_from_legacy(1, LEGACY_USER)
        assert user.school.url == "https://sgo.example.ru"
        assert user.school.name == "МОУ СОШ №1"
        assert user.credentials.login_type is LoginType.ESIA
        assert user.check_interval == 600
        assert user.student_name == "Иванов Иван"
        assert user.selected_student_id == 10
        assert len(user.available_students) == 2
        assert user.notifications.changes is False
        assert user.notifications.weekly_summary is True
        assert user.quiet_hours.start == dt.time(22, 0)

    def test_filters_are_normalized(self):
        user = user_from_legacy(1, LEGACY_USER)
        # Сравнение фильтров идёт по нормализованному виду, иначе «Ответ на
        # уроке» и «ответ на  уроке» считались бы разными.
        assert normalize("Ответ на уроке") in user.filters.exclude_titles
        assert user.filters.include_subjects == frozenset({normalize("Алгебра")})

    def test_minimal_record(self):
        # Самая старая запись: почти ничего не заполнено.
        user = user_from_legacy(2, {"login": "x"})
        assert user.enabled is False
        assert user.credentials.login_type is LoginType.PASSWORD
        assert user.quiet_hours.enabled is False
        assert user.available_students == ()

    def test_broken_values_do_not_crash(self):
        user = user_from_legacy(
            3,
            {
                "check_interval": "не число",
                "quiet_hours": {"start": "25:99", "end": ""},
                "available_students": ["мусор", {"id": "нет"}, {"id": 5, "name": "А"}],
                "filters": None,
                "subject_filters": {"include": None},
            },
        )
        assert user.check_interval == 300
        assert user.quiet_hours.enabled is False
        assert user.available_students == (Student(5, "А"),)
        assert user.filters.exclude_titles == frozenset()

    def test_out_of_range_interval_is_clamped(self):
        assert user_from_legacy(1, {"check_interval": 99999}).check_interval == 10800
        assert user_from_legacy(1, {"check_interval": 1}).check_interval == 180


class TestImport:
    async def test_users_are_imported(self, importer, users):
        report = await importer.run()
        assert report.users == 1
        loaded = await users.get(1)
        assert loaded is not None
        assert loaded.school.name == "МОУ СОШ №1"

    async def test_imported_user_starts_silent(self, importer, marks):
        """Ключи оценок несовместимы, поэтому первая проверка должна пройти
        молча — иначе человек получит весь журнал за год."""
        await importer.run()
        assert await marks.is_baseline_pending(1) is True
        assert await marks.has_history(1) is False

    async def test_mail_ids_are_carried_over(self, importer, marks):
        report = await importer.run()
        assert report.mail_ids == 3
        assert await marks.seen_mail_ids(1) == {101, 102, 103}

    async def test_sessions_are_imported(self, legacy_dir, importer, sessions):
        (legacy_dir / "netschool_sessions" / "session_1.json").write_text(
            '{"cookies": "abc"}', encoding="utf-8"
        )
        report = await importer.run()
        assert report.sessions == 1
        assert await sessions.load(1) == '{"cookies": "abc"}'

    async def test_sessions_of_unknown_users_are_ignored(self, legacy_dir, importer, sessions):
        (legacy_dir / "netschool_sessions" / "session_777.json").write_text("{}", encoding="utf-8")
        report = await importer.run()
        assert report.sessions == 0
        assert await sessions.load(777) is None

    async def test_tokens_keep_their_value(self, legacy_dir, importer, miniapp):
        """Ссылка на PWA уже сохранена у людей — токен обязан остаться тем же."""
        expires = int((dt.datetime.now() + dt.timedelta(days=200)).timestamp())
        (legacy_dir / "netschool_users" / "miniapp_tokens.json").write_text(
            json.dumps({"tokens": {"старый-токен": {"user_id": 1, "expires_at": expires}}}),
            encoding="utf-8",
        )
        report = await importer.run()
        assert report.tokens == 1
        assert await miniapp.resolve_token("старый-токен") == 1

    async def test_expired_tokens_are_skipped(self, legacy_dir, importer, miniapp):
        past = int((dt.datetime.now() - dt.timedelta(days=1)).timestamp())
        (legacy_dir / "netschool_users" / "miniapp_tokens.json").write_text(
            json.dumps({"tokens": {"протухший": {"user_id": 1, "expires_at": past}}}),
            encoding="utf-8",
        )
        report = await importer.run()
        assert report.tokens == 0
        assert await miniapp.resolve_token("протухший") is None

    async def test_missing_source_is_reported_not_crashed(self, tmp_path, users, marks, sessions, miniapp):
        importer = LegacyImporter(
            tmp_path / "нет-такого", users=users, state=marks, sessions=sessions, miniapp=miniapp
        )
        report = await importer.run()
        assert report.users == 0
        assert report.skipped

    async def test_corrupted_users_file_does_not_crash(
        self, legacy_dir, users, marks, sessions, miniapp
    ):
        (legacy_dir / "netschool_users" / "netschool_users.json").write_text(
            "{ это не json", encoding="utf-8"
        )
        importer = LegacyImporter(
            legacy_dir, users=users, state=marks, sessions=sessions, miniapp=miniapp
        )
        report = await importer.run()
        assert report.users == 0
        assert report.skipped

    async def test_bad_user_keys_are_skipped(self, legacy_dir, users, marks, sessions, miniapp):
        (legacy_dir / "netschool_users" / "netschool_users.json").write_text(
            json.dumps(
                {"users": {"не-число": LEGACY_USER, "2": LEGACY_USER, "3": "мусор"}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        importer = LegacyImporter(
            legacy_dir, users=users, state=marks, sessions=sessions, miniapp=miniapp
        )
        report = await importer.run()
        assert report.users == 1
        assert len(report.skipped) == 2

    async def test_rerun_is_idempotent(self, importer, users):
        await importer.run()
        second = await importer.run()
        assert second.users == 1
        assert len(await users.all_ids()) == 1

    async def test_report_is_readable(self, importer):
        report = await importer.run()
        text = report.as_text()
        assert "Пользователей перенесено: 1" in text
