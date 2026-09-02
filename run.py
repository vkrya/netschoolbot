#!/usr/bin/env python3
"""Точка входа NetSchool-бота.

Запускает Telegram-бота и (по умолчанию) веб-панель с PWA мини-приложением
в отдельном потоке.

    python run.py            # бот + веб
    python run.py --bot      # только бот
    python run.py --web      # только веб
"""

import asyncio
import sys
import threading

from netschoolbot import config
from netschoolbot.logging_setup import init_logging


def _start_web_thread(logger) -> None:
    from netschoolbot.web import run_web

    def _run() -> None:
        try:
            run_web()
        except Exception as exc:  # pragma: no cover
            logger.error(f"❌ Веб-сервер остановлен с ошибкой: {exc}", exc_info=exc)

    thread = threading.Thread(target=_run, name="WebServer", daemon=True)
    thread.start()
    logger.info(f"🌐 Веб-панель слушает порт {config.WEB_PORT} ({config.PUBLIC_BASE_URL})")


def main() -> None:
    config.ensure_data_dirs()
    logger = init_logging()

    only_bot = "--bot" in sys.argv
    only_web = "--web" in sys.argv

    if only_web:
        from netschoolbot.web import run_web

        logger.info(f"🌐 Запуск только веб-панели на порту {config.WEB_PORT}")
        run_web()
        return

    if config.WEB_ENABLED and not only_bot:
        _start_web_thread(logger)

    from netschoolbot.bot.app import run_bot

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("⏹ Остановка по Ctrl+C")


if __name__ == "__main__":
    main()
