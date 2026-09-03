"""Тесты разбора ответов netschoolpy.

Библиотека отдаёт оценку то объектом с textMark, то словарём, то числом, а
список детей — то словарём, то списком. Именно здесь раньше расходились
реализации бота и мини-приложения.
"""

import datetime as dt
from types import SimpleNamespace

import pytest

from app.domain.records import extract_mark, mark_to_int, parse_mark_float
from app.netschool.mapping import (
    diary_days,
    homework_from_day,
    marks_from_day,
    students_from_diary_init,
)


def assignment(**kwargs):
    return SimpleNamespace(
        **{
            "kind": "Контрольная работа",
            "content": "Дроби",
            "mark": 5,
            "weight": 2,
            "comment": "",
            "deadline": None,
            "attachments": [],
            **kwargs,
        }
    )


def lesson(assignments, subject="Алгебра", number=3):
    return SimpleNamespace(
        subject=subject,
        number=number,
        start=dt.time(9, 0),
        end=dt.time(9, 45),
        assignments=assignments,
    )


def day(lessons, date=dt.date(2026, 3, 2)):
    return SimpleNamespace(day=date, lessons=lessons)


class TestExtractMark:
    @pytest.mark.parametrize(
        "source,expected",
        [
            (5, "5"),
            ("4", "4"),
            (None, ""),
            ("", ""),
            ({"textMark": "зачтено"}, "зачтено"),
            ({"mark": 3}, "3"),
            ({"value": 4}, "4"),
            (SimpleNamespace(textMark="н/а", mark=None), "н/а"),
            (SimpleNamespace(mark=5), "5"),
            (True, ""),
        ],
    )
    def test_forms(self, source, expected):
        assert extract_mark(source) == expected

    def test_text_mark_wins_over_numeric(self):
        # У «зачтено» есть и числовое поле — показывать надо текст.
        assert extract_mark(SimpleNamespace(textMark="зачтено", mark=5)) == "зачтено"

    def test_no_infinite_recursion_on_self_reference(self):
        obj = SimpleNamespace(mark=None)
        obj.mark = obj
        assert extract_mark(obj) == ""

    @pytest.mark.parametrize(
        "raw,expected", [("5", 5), ("зачтено", None), ("4 (хорошо)", 4), ("0", None), ("10", 10)]
    )
    def test_to_int(self, raw, expected):
        assert mark_to_int(raw) == expected

    @pytest.mark.parametrize("raw,expected", [("4,5", 4.5), ("5", 5.0), ("зачтено", None)])
    def test_to_float(self, raw, expected):
        assert parse_mark_float(raw) == expected


class TestMarks:
    def test_basic_extraction(self):
        records = marks_from_day(day([lesson([assignment()])]))
        assert len(records) == 1
        record = records[0]
        assert record.subject == "Алгебра"
        assert record.mark == "5"
        assert record.weight == 2
        assert record.lesson_start == "09:00"
        assert record.title == "Контрольная работа Дроби"

    def test_assignments_without_mark_are_skipped(self):
        records = marks_from_day(day([lesson([assignment(mark=None), assignment(mark=4)])]))
        assert [r.mark for r in records] == ["4"]

    def test_index_distinguishes_assignments_in_one_lesson(self):
        records = marks_from_day(day([lesson([assignment(mark=5), assignment(mark=4)])]))
        assert {r.assignment_index for r in records} == {0, 1}
        assert records[0].identity != records[1].identity

    def test_empty_day_is_safe(self):
        assert marks_from_day(day([])) == []
        assert marks_from_day(SimpleNamespace(day=None, lessons=[])) == []

    def test_missing_lessons_attribute_is_safe(self):
        assert marks_from_day(SimpleNamespace(day=dt.date(2026, 3, 2), lessons=None)) == []

    def test_dict_shaped_input(self):
        raw = {
            "day": "2026-03-02",
            "lessons": [
                {
                    "subject": "Химия",
                    "number": 1,
                    "assignments": [{"kind": "Тест", "content": "Соли", "mark": 4}],
                }
            ],
        }
        records = marks_from_day(raw)
        assert records[0].subject == "Химия"
        assert records[0].mark == "4"


class TestHomework:
    TODAY = dt.date(2026, 3, 2)

    def test_basic(self):
        records = homework_from_day(
            day([lesson([assignment(content="Упр. 15", mark=None)])]), today=self.TODAY
        )
        assert len(records) == 1
        assert records[0].text == "Упр. 15"

    def test_far_future_is_ignored(self):
        far = self.TODAY + dt.timedelta(days=60)
        records = homework_from_day(
            day([lesson([assignment(content="Проект", deadline=far)])], date=far),
            today=self.TODAY,
        )
        assert records == []

    def test_old_homework_is_ignored(self):
        old = self.TODAY - dt.timedelta(days=10)
        records = homework_from_day(
            day([lesson([assignment(content="Старое", deadline=old)])], date=old),
            today=self.TODAY,
        )
        assert records == []

    def test_empty_content_without_attachments_is_skipped(self):
        records = homework_from_day(
            day([lesson([assignment(content="")])]), today=self.TODAY
        )
        assert records == []

    def test_placeholder_content_is_kept(self):
        # «---Не указана---» означает, что задание есть, а текста нет.
        records = homework_from_day(
            day([lesson([assignment(content="---Не указана---")])]), today=self.TODAY
        )
        assert [r.text for r in records] == ["Не указана"]

    def test_attachments_are_collected(self):
        att = SimpleNamespace(id=7, name="задание.pdf")
        records = homework_from_day(
            day([lesson([assignment(content="", attachments=[att])])]), today=self.TODAY
        )
        assert records[0].attachments[0].name == "задание.pdf"

    def test_attachment_without_name_gets_placeholder(self):
        att = SimpleNamespace(id=7, name=None)
        records = homework_from_day(
            day([lesson([assignment(content="", attachments=[att])])]), today=self.TODAY
        )
        assert records[0].attachments[0].name == "file_7"

    def test_identity_changes_with_attachments(self):
        plain = homework_from_day(
            day([lesson([assignment(content="Упр. 1")])]), today=self.TODAY
        )[0]
        with_file = homework_from_day(
            day([lesson([assignment(content="Упр. 1", attachments=[SimpleNamespace(id=1, name="a")])])]),
            today=self.TODAY,
        )[0]
        # Появившийся файл — повод сообщить заново.
        assert plain.identity != with_file.identity


class TestDiaryDays:
    def test_sorted_by_date(self):
        days = diary_days(
            [
                day([lesson([assignment()])], date=dt.date(2026, 3, 5)),
                day([lesson([assignment()])], date=dt.date(2026, 3, 2)),
            ],
            today=dt.date(2026, 3, 2),
        )
        assert [d.day for d in days] == [dt.date(2026, 3, 2), dt.date(2026, 3, 5)]

    def test_days_without_date_are_dropped(self):
        days = diary_days([SimpleNamespace(day=None, lessons=[])], today=dt.date(2026, 3, 2))
        assert days == []


class TestStudents:
    def test_dict_shape(self):
        students, current = students_from_diary_init(
            {"students": {"1": {"studentId": 10, "fio": "Иванов И."}}, "currentStudentId": 10}
        )
        assert students == [{"id": 10, "name": "Иванов И."}]
        assert current == 10

    def test_list_shape(self):
        students, current = students_from_diary_init(
            {"students": [{"studentId": 11, "fullName": "Петров П."}], "currentStudentId": 11}
        )
        assert students == [{"id": 11, "name": "Петров П."}]

    def test_missing_current_defaults_to_first(self):
        students, current = students_from_diary_init(
            {"students": [{"studentId": 12, "name": "А"}, {"studentId": 13, "name": "Б"}]}
        )
        assert current == 12

    def test_nameless_student_gets_placeholder(self):
        students, _ = students_from_diary_init({"students": [{"studentId": 14}]})
        assert students[0]["name"] == "Ученик 14"

    def test_empty_payload(self):
        assert students_from_diary_init({}) == ([], None)

    def test_garbage_entries_are_skipped(self):
        students, _ = students_from_diary_init({"students": ["мусор", {"studentId": 15, "fio": "В"}]})
        assert [s["id"] for s in students] == [15]
