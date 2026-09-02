"""Сборка и запуск Telegram-бота NetSchool."""

import asyncio
import logging
import signal
from typing import Optional

from aiogram import Bot, Dispatcher

from ..config import (
    ADMIN_ID,
    BOT_TOKEN,
    LOG_BOT_TOKEN,
)
from ..netschool.client import _close_all_netschool_sessions
from ..storage import load_netschool_users
from . import runtime
from .factory import create_tg_bot
from .handlers import auth, diary, gallery, menu, settings
from .runtime import netschool_user_tasks
from .tasks import start_all_user_grade_tasks, watch_external_netschool_user_updates

logger = logging.getLogger("netschoolbot")


def register_handlers(dp: Dispatcher, bot: Bot) -> None:
    """Порядок важен: `auth` содержит catch-all обработчик личных сообщений,
    поэтому регистрируется последним."""
    diary.register(dp, bot)
    menu.register(dp, bot)
    settings.register(dp, bot)
    gallery.register(dp, bot)
    auth.register(dp, bot)


async def run_bot() -> None:
    if not BOT_TOKEN:
        logger.error("❌ Не задан NETSCHOOL_BOT_TOKEN — бот не может быть запущен")
        return

    load_netschool_users()

    bot = create_tg_bot(BOT_TOKEN)
    dp = Dispatcher()

    log_bot: Optional[Bot] = None
    if LOG_BOT_TOKEN and LOG_BOT_TOKEN != BOT_TOKEN:
        log_bot = create_tg_bot(LOG_BOT_TOKEN)
    elif LOG_BOT_TOKEN:
        log_bot = bot

    runtime.set_bots(bot, log_bot, ADMIN_ID or None)
    register_handlers(dp, bot)
    logger.info("✅ Обработчики NetSchool зарегистрированы")

    stop_event = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except Exception:
                pass
    except Exception:
        pass

    tasks: list[asyncio.Task] = [
        asyncio.create_task(dp.start_polling(bot, skip_updates=True), name="Polling"),
    ]

    await start_all_user_grade_tasks(bot, log_bot, ADMIN_ID or None)
    tasks.extend(netschool_user_tasks.values())
    logger.info(f"✅ Запущено индивидуальных чекеров: {len(netschool_user_tasks)}")

    tasks.append(
        asyncio.create_task(
            watch_external_netschool_user_updates(bot, log_bot),
            name="NetSchoolUsersWatcher",
        )
    )

    stop_task = asyncio.create_task(stop_event.wait(), name="ShutdownSignal")
    try:
        alive = set(tasks)
        while alive:
            done, _pending = await asyncio.wait(alive | {stop_task}, return_when=asyncio.FIRST_COMPLETED)
            if stop_task in done:
                logger.warning("🛑 Получен сигнал остановки")
                break
            critical_failed = False
            for task in done:
                alive.discard(task)
                name = task.get_name()
                if task.cancelled():
                    logger.warning(f"🛑 Задача {name} отменена")
                    continue
                exc = task.exception()
                if exc:
                    logger.error(f"❌ Задача {name} завершилась с ошибкой: {exc!r}", exc_info=exc)
                else:
                    logger.warning(f"🛑 Задача {name} завершилась (result={task.result()!r})")
                # Падение polling'а критично, остальные задачи — нет
                if name == "Polling":
                    critical_failed = True
            if critical_failed:
                break
    except asyncio.CancelledError:
        pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        stop_task.cancel()

        try:
            await _close_all_netschool_sessions(keep_gosuslugi=True)
        except Exception as exc:
            logger.error(f"❌ Ошибка при закрытии сессий NetSchool: {exc}")

        for closable in (bot, log_bot):
            if closable is None:
                continue
            try:
                await closable.session.close()
            except Exception:
                pass
        logger.info("👋 Бот остановлен")
