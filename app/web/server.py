"""Веб-сервер мини-приложения.

aiohttp вместо Flask + flask-socketio + eventlet в отдельном потоке. Смысл
замены не в фреймворке, а в том, что теперь веб живёт в том же event loop,
что и бот: они делят один пул сессий «Сетевого города» и одно соединение с
базой, вместо того чтобы обмениваться данными через общие словари в памяти.

Панель управления (веб-терминал с PTY и файловый менеджер с корнем «/»)
не переносится: она держала доступ к серверу за паролем со значением по
умолчанию «adminpass».
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import aiohttp_jinja2
import jinja2
from aiohttp import web

from ..context import AppContext
from . import api
from .api import BOT, CONTEXT

logger = logging.getLogger("netschoolbot.web")

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Версия для обхода кэша браузера при обновлении статики.
STATIC_VERSION = str(int(time.time()))


def create_app(context: AppContext, bot=None) -> web.Application:
    app = web.Application(middlewares=[api.error_middleware, api.auth_middleware])
    app[CONTEXT] = context
    app[BOT] = bot

    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,  # шаблоны экранируют по умолчанию
    )

    app.add_routes(api.routes)
    app.add_routes(page_routes)
    app.router.add_static("/static", STATIC_DIR, name="static")
    return app


page_routes = web.RouteTableDef()


def _base(request: web.Request) -> str:
    """Префикс, под которым смонтировано приложение.

    Нужен потому, что nginx отдаёт PWA не с корня домена, и все ссылки внутри
    страницы должны учитывать этот префикс.
    """
    return request.app[CONTEXT].settings.web.miniapp_path.rstrip("/")


@page_routes.get("/")
@page_routes.get("/{tail:mini/netschool/?}")
async def index(request: web.Request) -> web.Response:
    """Страница приложения. Открывается по персональной ссылке с токеном."""
    context: AppContext = request.app[CONTEXT]
    token = (request.query.get("token") or request.cookies.get("netschool_token") or "").strip()
    telegram_id = await context.miniapp.resolve_token(token)

    if telegram_id is None:
        return aiohttp_jinja2.render_template(
            "link.html",
            request,
            {
                "base": _base(request),
                "version": STATIC_VERSION,
                "message": "Ссылка недействительна или была отозвана.",
            },
            status=401,
        )

    user = await context.users.get(telegram_id)
    response = aiohttp_jinja2.render_template(
        "app.html",
        request,
        {
            "base": _base(request),
            "version": STATIC_VERSION,
            "token": token,
            "student": user.student_name if user else "",
            "school": user.school.name if user else "",
            "push_enabled": context.settings.push.configured,
        },
    )
    response.set_cookie(
        "netschool_token",
        token,
        max_age=365 * 24 * 3600,
        httponly=True,
        samesite="Lax",
        secure=request.url.scheme == "https",
    )
    return response


@page_routes.get("/manifest.webmanifest")
async def manifest(request: web.Request) -> web.Response:
    context: AppContext = request.app[CONTEXT]
    token = (request.query.get("token") or "").strip()
    base = _base(request)
    user = None
    if telegram_id := await context.miniapp.resolve_token(token):
        user = await context.users.get(telegram_id)

    payload = {
        "name": user.school.name if user and user.school.name else "Сетевой город",
        "short_name": "Дневник",
        "description": "Дневник, оценки и домашние задания",
        # start_url с токеном: иначе установленное приложение открывалось бы
        # на странице «ссылка недействительна».
        "start_url": f"{base}/?token={token}" if token else f"{base}/",
        "scope": f"{base}/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#0d1117",
        "theme_color": "#0d1117",
        "lang": "ru",
        "icons": [
            {
                "src": f"{base}/static/icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            }
        ],
    }
    return web.json_response(payload, content_type="application/manifest+json")


@page_routes.get("/sw.js")
async def service_worker(request: web.Request) -> web.FileResponse:
    # Service worker обязан отдаваться с корня своей области видимости,
    # поэтому у него отдельный маршрут, а не путь внутри /static.
    return web.FileResponse(
        STATIC_DIR / "sw.js",
        headers={"Content-Type": "application/javascript; charset=utf-8",
                 "Service-Worker-Allowed": "/"},
    )


@page_routes.get("/health")
async def health(request: web.Request) -> web.Response:
    """Проверка живости для systemd и мониторинга."""
    context: AppContext = request.app[CONTEXT]
    return web.json_response(
        {
            "ok": True,
            "watchers": len(context.watchers.running),
            "sessions": len(context.pool._entries),
        }
    )


async def start_web(context: AppContext, bot=None) -> None:
    """Запустить сервер и держать его до отмены задачи."""
    settings = context.settings.web
    app = create_app(context, bot)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, settings.host, settings.port)
    await site.start()
    logger.info(
        "Мини-приложение слушает %s:%s (%s)", settings.host, settings.port, settings.miniapp_url
    )
    try:
        # Задача живёт, пока её не отменят при остановке процесса.
        while True:
            await _forever()
    finally:
        await runner.cleanup()


async def _forever() -> None:
    import asyncio

    await asyncio.sleep(3600)
