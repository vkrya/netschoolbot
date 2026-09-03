"""Логирование: файл, консоль и отправка ошибок админу в Telegram.

Отправка в Telegram сделана неблокирующей через очередь. В старой версии
хендлер писал в сеть прямо из вызова `logger.error`, поэтому недоступный
Telegram подвешивал ту самую задачу, которая пыталась сообщить о проблеме.
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
from pathlib import Path

from .settings import Settings

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Сколько сообщений держим в очереди на отправку админу. Дальше — отбрасываем:
# лавина ошибок не должна съесть память.
TELEGRAM_QUEUE_SIZE = 100


class TelegramHandler(logging.Handler):
    """Кладёт запись в очередь; отправкой занимается отдельная задача."""

    def __init__(self, queue: asyncio.Queue[str], level: int = logging.ERROR) -> None:
        super().__init__(level)
        self._queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:  # noqa: BLE001 — форматирование не должно ронять логгер
            return
        try:
            self._queue.put_nowait(message[:3500])
        except asyncio.QueueFull:
            # Очередь переполнена: сообщение теряется, но приложение живёт.
            pass


def setup_logging(settings: Settings) -> asyncio.Queue[str]:
    """Настроить логирование. Возвращает очередь сообщений для админа."""
    settings.ensure_dirs()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    for existing in list(root.handlers):
        root.removeHandler(existing)

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        settings.logs_dir / "netschoolbot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=TELEGRAM_QUEUE_SIZE)
    if settings.telegram.logging_enabled and settings.telegram.admin_id:
        telegram = TelegramHandler(queue)
        telegram.setFormatter(formatter)
        root.addHandler(telegram)

    # Чужие библиотеки многословны: их отладка нам не нужна.
    for noisy in ("aiogram.event", "aiohttp.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return queue


async def drain_to_telegram(queue: asyncio.Queue[str], bot, admin_id: int) -> None:
    """Отправлять накопленные ошибки админу. Запускается фоновой задачей."""
    logger = logging.getLogger("netschoolbot.logs")
    while True:
        message = await queue.get()
        try:
            await bot.send_message(admin_id, f"<pre>{message}</pre>", parse_mode="HTML")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Провал отправки лога нельзя логировать через тот же логгер —
            # получится бесконечная петля. Пишем напрямую в файл.
            logger.handlers and logger.debug("Не удалось отправить лог админу: %s", exc)
        finally:
            queue.task_done()
        # Telegram ограничивает частоту сообщений одному чату.
        await asyncio.sleep(1.0)
