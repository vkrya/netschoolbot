"""Фоновые задачи: индивидуальные чекеры оценок и повторные попытки входа."""

import asyncio
import copy
import html
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from aiogram import Bot

from ..config import (
    ADMIN_ID as TG_ADMIN_ID,
    BOT_TOKEN as NETSCHOOL_BOT_TOKEN,
    CHECK_INTERVAL,
    ERROR_NOTIFICATIONS_ENABLED,
    ERROR_NOTIFICATION_COOLDOWN,
    NETSCHOOL_USERS_DIR,
    USERS_FILE as NETSCHOOL_USERS_FILE,
)
from ..netschool.client import (
    _apply_selected_student_to_client,
    _classify_login_error,
    _close_netschool_client,
    _close_netschool_session_for_user,
    _fetch_student_name,
    _make_netschool,
    _netschool_session_is_alive,
    _netschool_session_path,
    _save_netschool_session,
    _sync_user_students_from_ns,
    _try_restore_netschool_session,
)
from ..netschool.notifier import GradeNotifier
from .. import storage
from ..storage import (
    _clamp_interval,
    _get_user_ns_school,
    _get_user_ns_url,
    _netschool_user_runtime_signature,
    get_netschool_user,
    get_user_exclude_titles,
    get_user_student_name,
    load_netschool_users,
    save_netschool_users,
)
from . import runtime
from .esia import _make_esia_mfa_callback
from .runtime import (
    netschool_login_retry_tasks,
    netschool_user_notifiers,
    netschool_user_tasks,
)

logger = logging.getLogger("netschoolbot")

last_error_notification_time: Dict[str, float] = {}


async def _notify_netschool_error(message: str) -> None:
    if not ERROR_NOTIFICATIONS_ENABLED:
        return
    key = "netschool_diary_error"
    now_ts = time.time()
    last_ts = last_error_notification_time.get(key, 0)
    if now_ts - last_ts < ERROR_NOTIFICATION_COOLDOWN:
        return
    last_error_notification_time[key] = now_ts
    target_bot = runtime.log_bot or runtime.bot
    if not target_bot or not TG_ADMIN_ID:
        return
    try:
        await target_bot.send_message(
            TG_ADMIN_ID,
            f"⚠️ <b>NetSchool:</b> {html.escape(str(message))}",
            parse_mode="HTML"
        )
    except Exception:
        pass

async def stop_user_grade_task(user_id: int) -> None:
    task = netschool_user_tasks.pop(user_id, None)
    notifier = netschool_user_notifiers.pop(user_id, None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if notifier and notifier._owns_bot:
        try:
            await notifier.bot.session.close()
        except Exception:
            pass
    await _close_netschool_session_for_user(user_id)

async def _prompt_user_to_finish_setup(user_id: int, what: str) -> None:
    """Сообщить пользователю, что нужно доввести настройки — ровно один раз.

    Раньше пустые регион и школа подменялись глобальными значениями из .env,
    поэтому часть людей никогда их не выбирала. Теперь подстановки нет, и без
    подсказки такой пользователь просто перестал бы получать оценки молча.
    """
    user_data = get_netschool_user(user_id)
    if user_data.get("setup_prompt_sent"):
        return
    target_bot = runtime.bot
    if not target_bot:
        return
    try:
        await target_bot.send_message(
            user_id,
            "⚠️ <b>Нужно выбрать школу заново</b>\n\n"
            f"Не заполнено: {what}.\n"
            "Раньше подставлялись общие настройки, теперь каждый указывает свою школу сам.\n\n"
            "Нажмите /login, выберите регион и школу — уведомления об оценках возобновятся.",
            parse_mode="HTML",
        )
        user_data["setup_prompt_sent"] = True
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        logger.info(f"📨 Пользователю {user_id} отправлена просьба выбрать школу ({what})")
    except Exception as exc:
        logger.warning(f"Не удалось предупредить пользователя {user_id} о настройке школы: {exc}")


async def start_user_grade_task(user_id: int, bot: Optional[Bot], log_bot: Optional[Bot], admin_id: Optional[int]) -> None:
    existing_task = netschool_user_tasks.get(user_id)
    if existing_task:
        if not existing_task.done():
            logger.info(f"🔁 Задача проверки оценок уже запущена для user {user_id}, повторный запуск пропущен")
            return
        netschool_user_tasks.pop(user_id, None)
        netschool_user_notifiers.pop(user_id, None)

    if not NETSCHOOL_BOT_TOKEN:
        logger.warning("⚠️ NETSCHOOL_BOT_TOKEN не задан, запуск пользователя невозможен")
        return

    user_data = get_netschool_user(user_id)
    if not user_data.get("enabled"):
        return
    if not user_data.get("login") or not user_data.get("password"):
        login_type = user_data.get("login_type", "password")
        if login_type != "esia_qr":
            return

    user_url = _get_user_ns_url(user_data)
    user_school = _get_user_ns_school(user_data)
    user_login_type = user_data.get("login_type", "password")
    if not user_url:
        logger.warning(f"⚠️ NetSchool URL не настроен для пользователя {user_id}")
        await _prompt_user_to_finish_setup(user_id, "регион (адрес «Сетевого города»)")
        return
    if user_login_type not in ("esia", "esia_qr") and not user_school:
        logger.warning(f"⚠️ NetSchool School не настроена для пользователя {user_id}")
        await _prompt_user_to_finish_setup(user_id, "школа")
        return

    # Настройки на месте — подсказку можно будет показать снова, если что-то отвалится
    if user_data.get("setup_prompt_sent"):
        user_data["setup_prompt_sent"] = False

    interval = _clamp_interval(int(user_data.get("check_interval") or CHECK_INTERVAL))
    user_data["check_interval"] = interval
    user_data["updated_at"] = datetime.now().isoformat()
    save_netschool_users()

    sent_grades_file = str(NETSCHOOL_USERS_DIR / f"sent_grades_{user_id}.json")
    known_grades_file = str(NETSCHOOL_USERS_DIR / f"known_grades_{user_id}.json")
    known_homework_file = str(NETSCHOOL_USERS_DIR / f"known_homework_{user_id}.json")
    ns_bot = None

    notifier = GradeNotifier(
        netschool_url=user_url,
        netschool_login=user_data.get("login"),
        netschool_password=user_data.get("password"),
        netschool_school=user_school,
        telegram_token=NETSCHOOL_BOT_TOKEN,
        telegram_chat_id=str(user_id),
        check_interval=interval,
        bot=ns_bot,
        log_bot=log_bot,
        admin_id=admin_id,
        user_id=user_id,
        user_display_name=get_user_student_name(user_id),
        exclude_titles=get_user_exclude_titles(user_data),
        sent_grades_file=sent_grades_file,
        known_grades_file=known_grades_file,
        known_homework_file=known_homework_file,
        message_thread_id=None,
        login_type=user_data.get("login_type", "password"),
    )

    netschool_user_notifiers[user_id] = notifier
    netschool_user_tasks[user_id] = asyncio.create_task(notifier.run(), name=f"NetSchoolUser:{user_id}")

async def refresh_user_grade_task(user_id: int, bot: Optional[Bot], log_bot: Optional[Bot], admin_id: Optional[int]) -> None:
    await stop_user_grade_task(user_id)
    await start_user_grade_task(user_id, bot, log_bot, admin_id)

async def stop_login_retry_task(user_id: int) -> None:
    task = netschool_login_retry_tasks.pop(user_id, None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

async def _login_retry_worker(user_id: int, bot: Bot) -> None:
    while True:
        user_data = get_netschool_user(user_id)
        login = user_data.get("login")
        password = user_data.get("password")
        login_type = user_data.get("login_type", "password")
        if login_type == "esia_qr":
            # QR-вход нельзя повторить автоматически
            return
        if not login or not password:
            return

        user_url = _get_user_ns_url(user_data)
        user_school = _get_user_ns_school(user_data)
        if not user_url:
            return
        if login_type != "esia" and not user_school:
            return
        ns_client = _make_netschool(user_url)
        try:
            if await _try_restore_netschool_session(user_id, ns_client):
                session_alive = await _netschool_session_is_alive(ns_client)
                if session_alive is not False:
                    _apply_selected_student_to_client(ns_client, user_data)
                    try:
                        await _sync_user_students_from_ns(ns_client, user_data, persist=True)
                    except Exception:
                        pass
                    user_data["enabled"] = True
                    user_data["bulk_prompt_pending"] = False
                    user_data["updated_at"] = datetime.now().isoformat()
                    save_netschool_users()
                    await refresh_user_grade_task(user_id, runtime.bot or bot, runtime.log_bot, TG_ADMIN_ID)
                    await bot.send_message(user_id, "✅ Сессия восстановлена. Уведомления включены.")
                    await stop_login_retry_task(user_id)
                    return
                try:
                    _netschool_session_path(user_id).unlink(missing_ok=True)
                except Exception:
                    pass
            if login_type == "esia":
                await ns_client.login_via_gosuslugi(
                    esia_login=login,
                    esia_password=password,
                    school=user_school or None,
                    timeout=60,
                    otp_callback=_make_esia_mfa_callback(user_id, bot),
                )
            else:
                await ns_client.login(
                    user_name=login,
                    password=password,
                    school=user_school
                )
            _save_netschool_session(user_id, ns_client)
            try:
                _apply_selected_student_to_client(ns_client, user_data)
                await _sync_user_students_from_ns(ns_client, user_data, persist=False)
                fio = await _fetch_student_name(ns_client)
                if fio:
                    user_data["student_name"] = fio
            except Exception:
                pass

            user_data["enabled"] = True
            user_data["bulk_prompt_pending"] = False
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            await refresh_user_grade_task(user_id, runtime.bot or bot, runtime.log_bot, TG_ADMIN_ID)
            await bot.send_message(user_id, "✅ Успешный вход. Уведомления включены.")
            await stop_login_retry_task(user_id)
            return
        except Exception as e:
            err_class = _classify_login_error(e)
            # MFA нельзя автоматически повторить — уведомляем пользователя
            from netschoolpy.exceptions import MFAError
            if isinstance(e, MFAError) or "MFAError" in type(e).__name__:
                logger.warning(f"Login retry for {user_id}: требуется MFA, автоповтор невозможен")
                await bot.send_message(
                    user_id,
                    "🔐 Для входа через Госуслуги необходим код подтверждения (SMS/TOTP/MAX).\n"
                    "Войдите вручную через /relogin — бот запросит код автоматически."
                )
                await stop_login_retry_task(user_id)
                return
            if err_class in ("esia", "server"):
                logger.debug(f"Login retry for {user_id}: {type(e).__name__}: {e}")
                await asyncio.sleep(180)
                continue
            logger.warning(f"Login retry for {user_id} permanent fail: {type(e).__name__}: {e}")
            login_type = user_data.get("login_type", "password")
            if login_type == "esia":
                await bot.send_message(user_id, "❌ Не удалось войти через Госуслуги. Проверьте логин/пароль и попробуйте снова через /relogin.")
            else:
                await bot.send_message(user_id, "❌ Не удалось войти в журнал. Проверьте логин/пароль и попробуйте снова через /relogin.")
            await stop_login_retry_task(user_id)
            return
        finally:
            try:
                await _close_netschool_client(ns_client, do_logout=False)
            except Exception:
                pass

async def start_login_retry_task(user_id: int, bot: Bot) -> None:
    await stop_login_retry_task(user_id)
    netschool_login_retry_tasks[user_id] = asyncio.create_task(_login_retry_worker(user_id, bot), name=f"NetSchoolLoginRetry:{user_id}")

async def start_all_user_grade_tasks(bot: Optional[Bot], log_bot: Optional[Bot], admin_id: Optional[int]) -> None:
    for key in list(storage.netschool_users.get("users", {}).keys()):
        try:
            user_id = int(key)
        except Exception:
            continue
        await start_user_grade_task(user_id, bot, log_bot, admin_id)

async def watch_external_netschool_user_updates(bot: Optional[Bot], log_bot: Optional[Bot]) -> None:
    while True:
        try:
            await asyncio.sleep(3)
            path = Path(NETSCHOOL_USERS_FILE)
            if not path.exists():
                continue
            current_mtime = path.stat().st_mtime
            if current_mtime <= storage.NETSCHOOL_USERS_FILE_MTIME:
                continue

            old_users = copy.deepcopy(storage.netschool_users.get("users", {}))
            load_netschool_users()
            new_users = storage.netschool_users.get("users", {})

            all_user_ids = set(old_users.keys()) | set(new_users.keys())
            for user_key in all_user_ids:
                try:
                    uid = int(user_key)
                except Exception:
                    continue
                old_user = old_users.get(user_key) or {}
                new_user = new_users.get(user_key) or {}
                if _netschool_user_runtime_signature(old_user) == _netschool_user_runtime_signature(new_user):
                    continue

                if not new_user or not bool(new_user.get("enabled")):
                    await stop_user_grade_task(uid)
                    continue

                await refresh_user_grade_task(uid, bot, log_bot, TG_ADMIN_ID)
                logger.info(f"🔄 Подхвачены внешние изменения NetSchool для пользователя {uid}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"❌ Ошибка отслеживания внешних изменений NetSchool: {e}")

