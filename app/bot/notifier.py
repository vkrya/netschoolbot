"""Доставка уведомлений в Telegram.

Реализация протокола `Notifier` из watcher.py. Вынесена отдельно, чтобы цикл
проверки оценок можно было тестировать без Telegram — в старом коде отправка
была вшита в тот же метод, что и вся логика.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from ..db.repositories import UserRepository
from ..domain import formatting
from ..domain.models import User
from ..domain.records import HomeworkRecord, MarkEvent
from ..netschool.errors import NetSchoolError

logger = logging.getLogger("netschoolbot.notifier")

# Больше этого числа событий — присылаем одну сводку вместо потока сообщений.
DIGEST_THRESHOLD = 5
BETWEEN_MESSAGES = 2.0


class TelegramNotifier:
    def __init__(self, bot: Bot, users: UserRepository) -> None:
        self._bot = bot
        self._users = users

    async def send_mark_events(self, user: User, events: list[MarkEvent]) -> None:
        if not events:
            return
        if len(events) > DIGEST_THRESHOLD:
            await self._send(user, formatting.mark_events_digest(events))
            return
        for index, event in enumerate(events):
            if index:
                await asyncio.sleep(BETWEEN_MESSAGES)
            await self._send(user, formatting.mark_event(event))

    async def send_homework(self, user: User, items: list[HomeworkRecord]) -> None:
        if items:
            await self._send(user, formatting.homework_digest(items))

    async def send_error(self, user: User, error: NetSchoolError) -> None:
        await self._send(user, f"⚠️ {formatting.esc(error.user_message)}")

    async def _send(self, user: User, text: str) -> None:
        """Отправить, разбив длинный текст и пережив ограничение частоты."""
        for part in formatting.split_message(text):
            await self._send_part(user, part)

    async def _send_part(self, user: User, text: str, *, retry: bool = True) -> None:
        try:
            await self._bot.send_message(user.telegram_id, text, parse_mode="HTML")
        except TelegramRetryAfter as exc:
            if not retry:
                logger.warning("Повторное ограничение частоты для %s", user.telegram_id)
                return
            await asyncio.sleep(exc.retry_after + 1)
            await self._send_part(user, text, retry=False)
        except TelegramForbiddenError:
            # Пользователь заблокировал бота: продолжать проверять его оценки
            # бессмысленно. Раньше такие пользователи оставались в цикле
            # навсегда и на каждом круге давали ошибку в логах.
            logger.info("Пользователь %s заблокировал бота — отключаем", user.telegram_id)
            from dataclasses import replace

            await self._users.save(replace(user, enabled=False))
