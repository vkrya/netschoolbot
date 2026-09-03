"""Тесты веб-приложения.

Проверяются, в частности, авторизация по токену и поведение при недоступной
школе: раньше при ошибке в браузер улетал то JSON, то HTML-страница Flask,
то текст исключения.
"""

import datetime as dt
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.context import AppContext
from app.domain.models import Student
from app.netschool.errors import NetSchoolError, Reason
from app.web.server import create_app
from tests.test_bot_handlers import app as app_context  # noqa: F401 — фикстура
from tests.test_repositories import make_user
from tests.test_watcher import record


@pytest.fixture
async def client(app_context) -> TestClient:
    server = TestServer(create_app(app_context))
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


@pytest.fixture
async def token(app_context, users):
    await users.save(make_user(student_name="Иванов И."))
    return await app_context.miniapp.issue_token(1)


class TestAuth:
    async def test_api_without_token_is_rejected(self, client):
        response = await client.get("/api/profile")
        assert response.status == 401
        body = await response.json()
        assert body["reason"] == "token"
        assert "/app" in body["error"]

    async def test_invalid_token_is_rejected(self, client):
        response = await client.get("/api/profile", params={"token": "выдумка"})
        assert response.status == 401

    async def test_valid_token_works(self, client, token):
        response = await client.get("/api/profile", params={"token": token})
        assert response.status == 200
        assert (await response.json())["data"]["name"] == "Иванов И."

    async def test_token_accepted_in_header(self, client, token):
        response = await client.get("/api/profile", headers={"X-Netschool-Token": token})
        assert response.status == 200

    async def test_token_moves_into_cookie(self, client, token):
        response = await client.get("/api/profile", params={"token": token})
        # Дальше токен не нужен в URL — он не утекает в историю и Referer.
        assert "netschool_token" in response.cookies

    async def test_revoked_token_stops_working(self, client, app_context, token):
        await app_context.miniapp.revoke_tokens(1)
        client.session.cookie_jar.clear()
        response = await client.get("/api/profile", params={"token": token})
        assert response.status == 401


class TestPages:
    async def test_index_without_token_shows_hint(self, client):
        response = await client.get("/")
        assert response.status == 401
        assert "Telegram" in await response.text()

    async def test_index_with_token_renders_app(self, client, token):
        response = await client.get("/", params={"token": token})
        assert response.status == 200
        text = await response.text()
        assert "Иванов И." in text
        assert "app.js" in text

    async def test_manifest_keeps_token_in_start_url(self, client, token):
        response = await client.get("/manifest.webmanifest", params={"token": token})
        payload = await response.json(content_type=None)
        # Иначе установленное на экран приложение открывалось бы на
        # странице «ссылка недействительна».
        assert token in payload["start_url"]

    async def test_service_worker_allows_root_scope(self, client):
        response = await client.get("/sw.js")
        assert response.status == 200
        assert response.headers["Service-Worker-Allowed"] == "/"

    async def test_health(self, client):
        response = await client.get("/health")
        assert (await response.json())["ok"] is True


class TestData:
    async def test_diary(self, client, app_context, token):
        app_context.diary.marks = [record(0)]
        response = await client.get("/api/diary", params={"token": token})
        assert response.status == 200
        assert (await response.json())["ok"] is True

    async def test_marks_are_grouped_with_averages(self, client, app_context, token):
        app_context.diary.marks = [
            record(0, "5", subject="Алгебра"),
            record(1, "3", subject="Алгебра"),
            record(2, "4", subject="Химия"),
        ]
        response = await client.get("/api/marks", params={"token": token})
        data = (await response.json())["data"]
        algebra = next(s for s in data["subjects"] if s["subject"] == "Алгебра")
        assert algebra["count"] == 2
        assert algebra["average"] == pytest.approx(4.0)

    async def test_homework(self, client, app_context, token):
        from app.domain.records import HomeworkRecord

        app_context.diary.homework = [
            HomeworkRecord("Алгебра", dt.date(2026, 3, 3), "ДЗ", "Упр. 1")
        ]
        response = await client.get("/api/homework", params={"token": token})
        items = (await response.json())["data"]["items"]
        assert items[0]["subject"] == "Алгебра"


class TestErrors:
    async def test_school_error_is_json_not_html(self, client, app_context, token):
        app_context.diary.error = NetSchoolError(Reason.SERVER_UNAVAILABLE, "Школа не отвечает")
        response = await client.get("/api/diary", params={"token": token})
        assert response.status == 503
        body = await response.json()
        assert body["ok"] is False
        assert body["reason"] == "server"

    async def test_auth_error_uses_401(self, client, app_context, token):
        app_context.diary.error = NetSchoolError(Reason.AUTH, "Войдите заново")
        response = await client.get("/api/diary", params={"token": token})
        assert response.status == 401
        assert (await response.json())["reason"] == "auth"

    async def test_unexpected_error_does_not_leak_details(self, client, app_context, token):
        app_context.diary.error = ValueError("пароль в тексте исключения")
        response = await client.get("/api/diary", params={"token": token})
        assert response.status == 500
        assert "пароль" not in await response.text()


class TestCache:
    async def test_second_request_uses_cache(self, client, app_context, token):
        app_context.diary.marks = [record(0)]
        await client.get("/api/marks", params={"token": token})
        # Школа отвалилась — но кэш свежий, ответ должен прийти как обычно.
        app_context.diary.error = NetSchoolError(Reason.SERVER_UNAVAILABLE, "лежит")
        response = await client.get("/api/marks", params={"token": token})
        body = await response.json()
        assert response.status == 200
        assert body["stale"] is False

    async def test_stale_cache_served_when_school_is_down(self, client, app_context, token):
        app_context.diary.marks = [record(0)]
        await client.get("/api/marks", params={"token": token})
        app_context.diary.error = NetSchoolError(Reason.SERVER_UNAVAILABLE, "лежит")
        # refresh обходит кэш по свежести, но при ошибке отдаётся сохранённое.
        response = await client.get("/api/marks", params={"token": token, "refresh": "1"})
        body = await response.json()
        assert response.status == 200
        assert body["stale"] is True
        assert body["reason"] == "server"

    async def test_no_cache_and_school_down_is_an_error(self, client, app_context, token):
        app_context.diary.error = NetSchoolError(Reason.SERVER_UNAVAILABLE, "лежит")
        response = await client.get("/api/marks", params={"token": token})
        assert response.status == 503


class TestStudentSwitch:
    async def test_switch_resets_tracking(self, client, app_context, users, marks, token):
        from app.domain.records import TrackedMark

        await users.save(
            make_user(
                available_students=(Student(10, "А"), Student(11, "Б")),
                selected_student_id=10,
            )
        )
        r = record(0)
        await marks.replace_marks(1, {r.identity: TrackedMark(r)})

        response = await client.post(
            "/api/student", params={"token": token}, json={"id": 11}
        )
        assert response.status == 200
        assert (await users.get(1)).selected_student_id == 11
        assert await marks.load_marks(1) == {}
        assert await marks.is_baseline_pending(1) is True

    async def test_unknown_student_is_rejected(self, client, users, token):
        await users.save(make_user(available_students=(Student(10, "А"),)))
        response = await client.post("/api/student", params={"token": token}, json={"id": 99})
        assert response.status == 404

    async def test_missing_id_is_rejected(self, client, token):
        response = await client.post("/api/student", params={"token": token}, json={})
        assert response.status == 400


class TestPush:
    async def test_key_unavailable_without_vapid(self, client, token):
        response = await client.get("/api/push/key", params={"token": token})
        assert response.status == 503

    async def test_subscribe_requires_complete_data(self, client, token):
        response = await client.post(
            "/api/push/subscribe", params={"token": token}, json={"endpoint": "https://x"}
        )
        assert response.status == 400

    async def test_subscribe_and_unsubscribe(self, client, app_context, token):
        payload = {
            "endpoint": "https://push.example/1",
            "keys": {"p256dh": "ключ", "auth": "секрет"},
        }
        response = await client.post("/api/push/subscribe", params={"token": token}, json=payload)
        assert response.status == 200
        assert len(await app_context.miniapp.push_subscriptions(1)) == 1

        await client.post(
            "/api/push/unsubscribe",
            params={"token": token},
            json={"endpoint": payload["endpoint"]},
        )
        assert await app_context.miniapp.push_subscriptions(1) == []
