"""Правки поведения ЕСИА-входа в netschoolpy.

Две проблемы боевого входа через Госуслуги, которые чинятся здесь без правки
самой библиотеки:

1. **HTTP 202 на проверке кода.** После верного SMS/TOTP/MAX-кода ЕСИА
   отвечает ``202 Accepted`` и телом со следующим шагом (например
   ``{"action": "MAX_QUIZ", ...}``). netschoolpy считает успехом только
   200/201, поэтому корректный код превращался в
   ``Ошибка подтверждения кода: 202 {"action":"MAX_QUIZ", ...}``.
   Неверный код ЕСИА отдаёт иначе — 200 с полем ``failed``, — так что 202
   без ``failed`` безопасно считать успехом.

2. **MAX_QUIZ.** После входа ЕСИА предлагает подтвердить вход в приложении
   «МАКС». netschoolpy пробует пропустить этот шаг только при
   ``max_details.skippable``, которого в ответе может не быть, и сразу
   падает с советом «настройте Госключ». Пробуем пропустить шаг в любом
   случае, а если ЕСИА не разрешает — отдаём понятное сообщение.
"""

import json
import logging

logger = logging.getLogger("netschoolbot")

ESIA_LOGIN_API = "https://esia.gosuslugi.ru/aas/oauth2/api/login"

_applied = False


def _response_is_esia_next_step(response) -> bool:
    """202 от ЕСИА с телом следующего шага (а не с ошибкой)."""
    try:
        data = response.json()
    except Exception:
        return False
    if not isinstance(data, dict) or data.get("failed"):
        return False
    return bool(data.get("action") or data.get("redirect_url"))


def _patch_httpx_202() -> None:
    """202 от ЕСИА на шагах входа приравниваем к 200."""
    import httpx

    original_post = httpx.AsyncClient.post

    async def _post(self, url, *args, **kwargs):
        response = await original_post(self, url, *args, **kwargs)
        try:
            if (
                response.status_code == 202
                and str(url).startswith(ESIA_LOGIN_API)
                and _response_is_esia_next_step(response)
            ):
                logger.info("ЕСИА ответила 202 со следующим шагом — считаем код принятым")
                response.status_code = 200
        except Exception:  # pragma: no cover — патч не должен ломать запрос
            pass
        return response

    _post.__netschoolbot_patched__ = True
    if not getattr(httpx.AsyncClient.post, "__netschoolbot_patched__", False):
        httpx.AsyncClient.post = _post


def _patch_max_quiz() -> None:
    """Пробуем пропустить MAX_QUIZ даже без флага ``skippable``."""
    from netschoolpy import client as ns_client
    from netschoolpy import exceptions

    original_post_mfa = ns_client.NetSchool._handle_esia_post_mfa

    async def _handle_esia_post_mfa(self, esia_client, data, otp_callback=None):
        if isinstance(data, dict) and data.get("action") == "MAX_QUIZ":
            details = data.get("max_details") or {}
            if not details.get("skippable"):
                logger.info("ЕСИА просит подтверждение через «МАКС» — пробуем пропустить шаг")
                resp = await esia_client.post(
                    f"{ESIA_LOGIN_API}/quiz-max/skip",
                    json={},
                    headers=ns_client._ESIA_API_HEADERS,
                )
                if resp.status_code in (200, 201, 202):
                    try:
                        data = resp.json()
                    except (json.JSONDecodeError, ValueError):
                        data = {}
                else:
                    # Именно MFAError: автоповтор входа тут не поможет, нужен
                    # шаг со стороны пользователя.
                    raise exceptions.MFAError(
                        "Госуслуги требуют подтвердить вход в приложении «МАКС», "
                        "и пропустить этот шаг нельзя. Подтвердите вход в «МАКС» "
                        "или войдите по QR-коду Госуслуг."
                    )
        return await original_post_mfa(self, esia_client, data, otp_callback=otp_callback)

    _handle_esia_post_mfa.__netschoolbot_patched__ = True
    if not getattr(ns_client.NetSchool._handle_esia_post_mfa, "__netschoolbot_patched__", False):
        ns_client.NetSchool._handle_esia_post_mfa = _handle_esia_post_mfa


def apply() -> None:
    """Применить правки. Безопасно вызывать несколько раз."""
    global _applied
    if _applied:
        return
    try:
        _patch_httpx_202()
        _patch_max_quiz()
    except Exception as exc:  # pragma: no cover
        logger.warning(f"Не удалось пропатчить ЕСИА-вход netschoolpy: {exc}")
        return
    _applied = True
