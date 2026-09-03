"""HTTP API мини-приложения.

Раньше это был файл на 2953 строки, в котором каждый обработчик сам ходил в
«Сетевой город» через `asyncio.run()` — то есть на каждый запрос создавался
новый event loop, а соединения не переиспользовались. Теперь обработчики
асинхронные и работают через общий сервис дневника.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import asdict, replace

from aiohttp import web

from ..context import AppContext
from ..domain import formatting
from ..domain.models import User, normalize
from ..domain.records import DiaryDay
from ..netschool.errors import NetSchoolError, Reason
from ..netschool.service import msk_today

logger = logging.getLogger("netschoolbot.web")

routes = web.RouteTableDef()

# Типизированные ключи вместо строк: aiohttp так избегает конфликтов имён
# между приложением и подключёнными к нему библиотеками.
CONTEXT = web.AppKey("context", AppContext)
BOT = web.AppKey("bot", object)
USER = web.RequestKey("netschool_user", User)
TOKEN = web.RequestKey("netschool_token", str)


def context(request: web.Request) -> AppContext:
    return request.app[CONTEXT]


def current_user(request: web.Request) -> User:
    """Пользователь запроса. Проставляется middleware авторизации."""
    return request[USER]


def json_error(message: str, *, status: int = 400, reason: str = "") -> web.Response:
    return web.json_response(
        {"ok": False, "error": message, "reason": reason}, status=status
    )


@web.middleware
async def error_middleware(request: web.Request, handler):
    """Единая обработка ошибок API.

    Раньше каждый обработчик ловил исключения сам, по-своему, и в браузер
    улетал то JSON, то HTML-страница ошибки Flask, то текст исключения.
    """
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except NetSchoolError as exc:
        status = 401 if exc.reason.needs_relogin else 503
        return json_error(exc.user_message, status=status, reason=exc.reason.value)
    except Exception:
        logger.exception("Ошибка в %s %s", request.method, request.path)
        return json_error("Внутренняя ошибка. Она записана, я разберусь.", status=500)


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Проверка токена доступа.

    Токен приходит либо в заголовке, либо в query — второе нужно, потому что
    PWA открывается по ссылке из Telegram, где заголовок задать негде.
    """
    if not request.path.startswith("/api/"):
        return await handler(request)

    token = (
        request.headers.get("X-Netschool-Token")
        or request.query.get("token")
        or request.cookies.get("netschool_token")
        or ""
    ).strip()

    telegram_id = await context(request).miniapp.resolve_token(token)
    if telegram_id is None:
        return json_error("Ссылка недействительна. Запросите новую: /app", status=401,
                          reason="token")

    user = await context(request).users.get(telegram_id)
    if user is None:
        return json_error("Пользователь не найден", status=401, reason="token")

    request[USER] = user
    request[TOKEN] = token
    response = await handler(request)
    # Токен кладётся в cookie, чтобы дальнейшие запросы шли без него в URL
    # и ссылка не утекала в историю браузера и в Referer.
    response.set_cookie(
        "netschool_token",
        token,
        max_age=365 * 24 * 3600,
        httponly=True,
        samesite="Lax",
        secure=request.url.scheme == "https",
    )
    return response


def _day_to_json(day: DiaryDay) -> dict:
    return {
        "date": day.day.isoformat(),
        "label": formatting.date_label(day.day),
        "marks": [
            {
                "subject": record.subject,
                "title": record.title,
                "mark": record.mark,
                "weight": record.weight,
                "numeric": record.numeric_mark,
            }
            for record in day.marks
        ],
        "homework": [
            {
                "subject": item.subject,
                "text": item.text,
                "attachments": [
                    {"id": a.id, "name": a.name} for a in item.attachments
                ],
            }
            for item in day.homework
        ],
    }


async def _cached(request: web.Request, section: str, producer):
    """Отдать свежий кэш или сходить за данными и обновить его.

    Если школьный сервер недоступен, отдаётся устаревший кэш с пометкой —
    приложение продолжает работать, а не показывает пустой экран.
    """
    app = context(request)
    user = current_user(request)
    cached = await app.cache.get(user.telegram_id, section)
    fresh_for = dt.timedelta(seconds=app.settings.web.cache_fresh_seconds)

    if cached is not None and not request.query.get("refresh"):
        payload, updated = cached
        if dt.datetime.now() - updated < fresh_for:
            return web.json_response({"ok": True, "data": payload, "stale": False})

    try:
        payload = await producer(app, user)
    except NetSchoolError as exc:
        if cached is None:
            raise
        logger.info("Отдаю устаревший кэш %s для %s: %s", section, user.telegram_id, exc.reason)
        return web.json_response(
            {"ok": True, "data": cached[0], "stale": True, "reason": exc.reason.value}
        )

    await app.cache.put(user.telegram_id, section, payload)
    return web.json_response({"ok": True, "data": payload, "stale": False})


@routes.get("/api/profile")
async def profile(request: web.Request) -> web.Response:
    user = current_user(request)
    return web.json_response(
        {
            "ok": True,
            "data": {
                "name": user.label,
                "school": user.school.name,
                "students": [
                    {"id": s.id, "name": s.name, "current": s.id == user.selected_student_id}
                    for s in user.available_students
                ],
                "notifications": asdict(user.notifications),
                "interval_minutes": user.check_interval // 60,
                "quiet_hours": user.quiet_hours.as_text(),
                "enabled": user.enabled,
            },
        }
    )


@routes.get("/api/diary")
async def diary(request: web.Request) -> web.Response:
    async def produce(app: AppContext, user: User):
        days = await app.diary.fetch_diary(user, weeks_back=2, weeks_forward=2)
        return {"days": [_day_to_json(day) for day in days]}

    return await _cached(request, "diary", produce)


@routes.get("/api/marks")
async def marks(request: web.Request) -> web.Response:
    async def produce(app: AppContext, user: User):
        records = await app.diary.fetch_marks(user)
        by_subject: dict[str, list] = {}
        for record in records:
            by_subject.setdefault(record.subject, []).append(record)

        subjects = []
        for subject, items in sorted(by_subject.items()):
            subjects.append(
                {
                    "subject": subject,
                    "average": formatting.weighted_average(items),
                    "count": len(items),
                    "marks": [
                        {
                            "date": r.date.isoformat(),
                            "title": r.title,
                            "mark": r.mark,
                            "weight": r.weight,
                        }
                        for r in sorted(items, key=lambda r: r.date)
                    ],
                }
            )
        return {"subjects": subjects, "average": formatting.weighted_average(records)}

    return await _cached(request, "marks", produce)


@routes.get("/api/homework")
async def homework(request: web.Request) -> web.Response:
    async def produce(app: AppContext, user: User):
        items = await app.diary.fetch_homework(user, weeks_back=0, weeks_forward=2)
        return {
            "items": [
                {
                    "date": item.due_date.isoformat(),
                    "label": formatting.date_label(item.due_date),
                    "subject": item.subject,
                    "text": item.text,
                    "attachments": [{"id": a.id, "name": a.name} for a in item.attachments],
                }
                for item in sorted(items, key=lambda h: (h.due_date, h.subject))
            ]
        }

    return await _cached(request, "homework", produce)


@routes.get("/api/mail")
async def mail(request: web.Request) -> web.Response:
    async def produce(app: AppContext, user: User):
        return {"messages": await app.diary.fetch_mail(user)}

    return await _cached(request, "mail", produce)


@routes.get("/api/attachment/{attachment_id}")
async def attachment(request: web.Request) -> web.Response:
    try:
        attachment_id = int(request.match_info["attachment_id"])
    except ValueError:
        return json_error("Некорректный идентификатор вложения")

    app, user = context(request), current_user(request)
    payload = await app.diary.download_attachment(user, attachment_id)
    return web.Response(
        body=payload,
        headers={
            # Имя файла не подставляем из данных школы: оно приходит извне и
            # в заголовке требует отдельного экранирования.
            "Content-Disposition": f'attachment; filename="attachment-{attachment_id}"'
        },
    )


@routes.post("/api/student")
async def switch_student(request: web.Request) -> web.Response:
    app, user = context(request), current_user(request)
    body = await request.json()
    try:
        student_id = int(body["id"])
    except (KeyError, TypeError, ValueError):
        return json_error("Не указан ученик")

    student = next((s for s in user.available_students if s.id == student_id), None)
    if student is None:
        return json_error("Такого ученика нет в аккаунте", status=404)

    updated = await app.users.save(
        replace(user, selected_student_id=student.id, student_name=student.name)
    )
    # Тот же сброс, что и в боте: журнал другого ребёнка иначе приедет
    # как «новые оценки».
    await app.state.forget_all(updated.telegram_id)
    await app.state.mark_baseline_pending(updated.telegram_id, True)
    await app.cache.clear(updated.telegram_id)
    await app.pool.invalidate(updated.telegram_id)
    return web.json_response({"ok": True, "data": {"name": student.name}})


@routes.get("/api/push/key")
async def push_key(request: web.Request) -> web.Response:
    settings = context(request).settings.push
    if not settings.configured:
        return json_error("Push-уведомления не настроены", status=503)
    return web.json_response({"ok": True, "data": {"key": settings.public_key}})


@routes.post("/api/push/subscribe")
async def push_subscribe(request: web.Request) -> web.Response:
    app, user = context(request), current_user(request)
    body = await request.json()
    endpoint = str(body.get("endpoint") or "").strip()
    keys = body.get("keys") or {}
    p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")

    if not endpoint or not p256dh or not auth:
        return json_error("Неполные данные подписки")

    await app.miniapp.add_push_subscription(user.telegram_id, endpoint, p256dh, auth)
    return web.json_response({"ok": True})


@routes.post("/api/push/unsubscribe")
async def push_unsubscribe(request: web.Request) -> web.Response:
    body = await request.json()
    endpoint = str(body.get("endpoint") or "").strip()
    if endpoint:
        await context(request).miniapp.drop_push_subscription(endpoint)
    return web.json_response({"ok": True})
