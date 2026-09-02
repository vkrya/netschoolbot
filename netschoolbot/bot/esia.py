"""Госуслуги (ЕСИА): запрос кода подтверждения у пользователя."""

import asyncio
import logging

from aiogram import Bot

from ..netschool.client import esia_otp_futures
from ..storage import set_netschool_user_state
from .keyboards import _kb_back_cancel

logger = logging.getLogger("netschoolbot")


def _make_esia_mfa_callback(user_id: int, send_bot: "Bot"):
    """Создаёт async-callback для MFA Госуслуг: отправляет пользователю
    сообщение с просьбой ввести код и ждёт его ответа (до 5 мин)."""
    async def _otp_callback(mfa_type: str, mfa_info: dict) -> str:
        type_labels = {
            "SMS":  "📱 SMS-код",
            "MAX":  "📲 Код из приложения «Макс»",
            "TOTP": "🔐 Код из приложения-аутентификатора",
        }
        label = type_labels.get(mfa_type, f"🔐 Код подтверждения (тип: {mfa_type})")
        phone = mfa_info.get("phone", "")
        code_len = mfa_info.get("code_length", 6)
        phone_part = f" на номер {phone}" if phone else ""
        await send_bot.send_message(
            user_id,
            f"{label}{phone_part} ({code_len} цифр).\n\n"
            "Отправьте его сюда — сообщение удалится автоматически.",
            reply_markup=_kb_back_cancel()
        )
        set_netschool_user_state(user_id, "await_esia_otp")
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        esia_otp_futures[user_id] = fut
        try:
            code = await asyncio.wait_for(asyncio.shield(fut), timeout=300)
        except asyncio.TimeoutError:
            esia_otp_futures.pop(user_id, None)
            set_netschool_user_state(user_id, None)
            raise Exception("Время ввода кода истекло (5 мин). Попробуйте снова через /relogin.")
        except asyncio.CancelledError:
            raise Exception("Ввод отменён пользователем.")
        return code
    return _otp_callback

