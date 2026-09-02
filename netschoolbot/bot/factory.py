"""Создание экземпляров aiogram Bot."""

import logging

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from ..config import TELEGRAM_API_PROXY

logger = logging.getLogger("netschoolbot")


def create_tg_bot(token: str) -> Bot:
    """Создаёт aiogram-бота, при необходимости через прокси."""
    proxy = TELEGRAM_API_PROXY
    if proxy:
        # aiohttp/aiogram ожидают схему socks5 для SOCKS-прокси.
        proxy = proxy.replace("socks5h://", "socks5://")
        logger.info(f"🌐 Telegram Bot API proxy enabled: {proxy}")
        return Bot(token=token, session=AiohttpSession(proxy=proxy))
    return Bot(token=token)
