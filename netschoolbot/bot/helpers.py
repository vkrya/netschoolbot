"""Вспомогательные функции обработчиков: получение клиента NetSchool,
отправка дневника/расписания/почты, вход в «Сетевой город»."""

import asyncio
import html
import io
import json
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from io import BytesIO
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from netschoolpy import NetSchool
import netschoolpy.exceptions as netschoolpy_exceptions

from ..config import ADMIN_ID as TG_ADMIN_ID, CHECK_INTERVAL
from ..netschool import client as ns_client
from ..netschool.client import (
    _apply_selected_student_to_client,
    _close_netschool_client,
    _close_netschool_session_for_user,
    _fetch_days_for_period,
    _fetch_diary_days,
    _fetch_student_name,
    _make_netschool,
    _netschool_session_is_alive,
    _save_netschool_session,
    _sync_user_students_from_ns,
    _try_restore_netschool_session,
    _classify_login_error,
    _close_netschool_session,
    _netschool_session_path,
    is_esia_connection_error,
    is_netschool_auth_error,
    is_server_unavailable_error,
    NETSCHOOL_SESSION_CACHE,
    NETSCHOOL_SESSION_TTL,
    _ns_clients,
    esia_otp_futures,
)
from ..netschool.grades import (
    _collect_grades,
    _load_netschool_cache,
    _refresh_user_cache_from_days,
    _render_grades_text,
    _render_homework_text,
    _render_schedule_text,
    _save_netschool_cache,
    _iter_grade_entries,
)
from ..storage import (
    _build_netschool_miniapp_url,
    _clamp_interval,
    _get_available_students,
    _get_user_ns_school,
    _get_user_ns_url,
    _issue_netschool_miniapp_token,
    _load_pwa_gallery,
    _pwa_gallery_image_path,
    format_user_quiet_hours,
    get_netschool_user,
    get_user_exclude_titles,
    get_user_student_name,
    get_user_subject_include_titles,
    save_netschool_users,
    set_netschool_user_state,
)
from ..utils import (
    _current_quarter_start,
    _safe_int,
    _extract_mark_value,
    _file_count_label,
    _format_date_label,
    _match_subject,
    _normalize_subject,
    _next_three_days,
    _quarter_start_for_user,
    _split_message,
)
from . import runtime
from .tasks import start_user_grade_task
from .esia import _make_esia_mfa_callback
from .keyboards import (
    _build_calendar_keyboard,
    _build_date_choice_keyboard,
    _build_grades_subjects_keyboard,
    _build_netschool_control_center_keyboard,
    _build_netschool_control_center_text,
    _build_netschool_main_menu,
    _build_pwa_gallery_preview_keyboard,
    _build_student_switch_keyboard,
    _insert_child_switch_row,
    _kb_back_cancel,
    _kb_back_to_login,
    _kb_cancel_action,
)

logger = logging.getLogger("netschoolbot")


async def _send_pwa_gallery_previews(message: Message, *, mode: str = "all") -> None:
    icons = list(reversed(_load_pwa_gallery()))
    if not icons:
        await message.answer("📂 Галерея пуста.")
        return
    await message.answer(
        "🖼 Предпросмотр последних иконок из галереи.\n"
        "Используйте кнопки под картинкой для удаления публикации или отзыва токенов владельца."
    )
    sent = 0
    for icon in icons[:12]:
        gallery_id = str(icon.get("id") or "")
        image_path = _pwa_gallery_image_path(gallery_id)
        if not image_path.exists():
            continue
        owner_id = int(icon.get("user_id") or 0)
        created_at = str(icon.get("created_at") or "")
        created_label = html.escape(created_at[:19].replace("T", " ")) if created_at else "—"
        caption = (
            "🖼 <b>PWA-иконка</b>\n"
            f"ID: <code>{html.escape(gallery_id)}</code>\n"
            f"Владелец: <code>{owner_id}</code>\n"
            f"Опубликована: {created_label}"
        )
        await message.answer_photo(
            FSInputFile(image_path),
            caption=caption,
            parse_mode="HTML",
            reply_markup=_build_pwa_gallery_preview_keyboard(icon, mode=mode),
        )
        sent += 1
    if not sent:
        await message.answer("📂 В галерее есть записи, но файлов иконок уже нет.")

async def _ensure_student_selected(ns: NetSchool, user_data: Dict[str, Any]) -> None:
    if getattr(ns, "students", None):
        user_data["role"] = "parent"
    else:
        user_data["role"] = "student"
        
    saved_student_id = user_data.get("netschool_student_id")
    if saved_student_id and getattr(ns, '_student_id', None) != saved_student_id:
        try:
            await ns.switch_student(saved_student_id)
        except Exception as e:
            logger.warning(f"Could not switch to student {saved_student_id}: {e}")

async def _get_ns_client(message: Message, user_id: Optional[int] = None) -> Optional[NetSchool]:
    user_id = user_id or message.from_user.id
    user_data = get_netschool_user(user_id)
    if not user_data.get("enabled"):
        await message.reply("❌ Уведомления отключены. Включите их через /on.")
        return None
    login = user_data.get("login")
    password = user_data.get("password")
    login_type = user_data.get("login_type", "password")
    if login_type == "esia_qr":
        # QR-пользователи — только кэшированная сессия
        cached = NETSCHOOL_SESSION_CACHE.get(user_id)
        if cached:
            last_used = cached.get("last_used")
            if isinstance(last_used, datetime) and (datetime.now() - last_used).total_seconds() <= NETSCHOOL_SESSION_TTL:
                ns = cached.get("client")
                if ns:
                    session_alive = await _netschool_session_is_alive(ns)
                    if session_alive is not False:
                        _apply_selected_student_to_client(ns, user_data)
                        cached["last_used"] = datetime.now()
                        setattr(ns, "_from_cache", True)
                        await _ensure_student_selected(ns, user_data)
                        return ns
            await _close_netschool_session(user_id)
        # Также проверяем _ns_clients
        ns = _ns_clients.get(user_id)
        if ns:
            session_alive = await _netschool_session_is_alive(ns)
            if session_alive is not False:
                _apply_selected_student_to_client(ns, user_data)
                NETSCHOOL_SESSION_CACHE[user_id] = {"client": ns, "last_used": datetime.now()}
                setattr(ns, "_from_cache", True)
                await _ensure_student_selected(ns, user_data)
                return ns
        await message.reply("❌ Сессия QR-входа истекла. Используйте /relogin для повторного входа.")
        return None
    if not login or not password:
        await message.reply("❌ Логин или пароль не указаны. Установите их через /login.")
        return None
    cached = NETSCHOOL_SESSION_CACHE.get(user_id)
    if cached:
        last_used = cached.get("last_used")
        if isinstance(last_used, datetime) and (datetime.now() - last_used).total_seconds() <= NETSCHOOL_SESSION_TTL:
            ns = cached.get("client")
            if ns:
                session_alive = await _netschool_session_is_alive(ns)
                if session_alive is not False:
                    _apply_selected_student_to_client(ns, user_data)
                    cached["last_used"] = datetime.now()
                    setattr(ns, "_from_cache", True)
                    await _ensure_student_selected(ns, user_data)
                    return ns
        await _close_netschool_session(user_id)

    user_url = _get_user_ns_url(user_data)
    user_school = _get_user_ns_school(user_data)
    login_type = user_data.get("login_type", "password")
    if not user_url:
        await message.reply("❌ Регион не настроен. Используйте /login для настройки.")
        return None
    if login_type == "esia_qr":
        await message.reply("❌ Сессия QR-входа истекла. Используйте /relogin для повторного входа.")
        return None
    if login_type != "esia" and not user_school:
        await message.reply("❌ Школа не настроена. Используйте /login для настройки.")
        return None
    ns = _make_netschool(user_url)
    
    # Пытаемся восстановить сохраненную сессию перед новым логином
    if await _try_restore_netschool_session(user_id, ns):
        session_alive = await _netschool_session_is_alive(ns)
        if session_alive is not False:
            _apply_selected_student_to_client(ns, user_data)
            try:
                await _sync_user_students_from_ns(ns, user_data, persist=True)
            except Exception:
                pass
            NETSCHOOL_SESSION_CACHE[user_id] = {
                "client": ns,
                "last_used": datetime.now()
            }
            setattr(ns, "_from_cache", True)
            await _ensure_student_selected(ns, user_data)
            return ns
        try:
            _netschool_session_path(user_id).unlink(missing_ok=True)
        except Exception:
            pass
    
    try:
        if login_type == "esia":
            await ns.login_via_gosuslugi(esia_login=login, esia_password=password, school=user_school or None, timeout=60,
                otp_callback=_make_esia_mfa_callback(user_id, runtime.bot))
        else:
            await ns.login(user_name=login, password=password, school=user_school)
        
        await _ensure_student_selected(ns, user_data)
        # Сохраняем сессию после успешного логина
        try:
            await _sync_user_students_from_ns(ns, user_data, persist=True)
        except Exception:
            pass
        _save_netschool_session(user_id, ns)
    except Exception as e:
        error_text = str(e)
        if is_server_unavailable_error(e) or "Expecting value" in error_text or "JSON" in error_text or "All connection attempts failed" in error_text:
            await message.reply("❌ Ошибка входа в журнал: сервис временно недоступен. Попробуйте позже.")
        elif is_netschool_auth_error(e):
            try:
                _netschool_session_path(user_id).unlink(missing_ok=True)
            except Exception:
                pass
            NETSCHOOL_SESSION_CACHE.pop(user_id, None)
            _ns_clients.pop(user_id, None)
            await message.reply(
                "❌ Сессия или данные входа в NetSchool больше не подходят.\n\n"
                "Используйте /relogin и выберите школу заново."
            )
        else:
            await message.reply("❌ Ошибка входа в журнал. Попробуйте снова через /relogin.")
            logger.warning(f"NetSchool login error for {user_id}: {type(e).__name__}: {e}")
        try:
            await _close_netschool_client(ns, do_logout=False)
        except Exception:
            pass
        return None
    NETSCHOOL_SESSION_CACHE[user_id] = {
        "client": ns,
        "last_used": datetime.now()
    }
    setattr(ns, "_from_cache", True)
    return ns

async def _send_homework_for_dates(
    message: Message,
    target_dates: set,
    header: str,
    user_id: Optional[int] = None
) -> None:
    # При вызове из callback message — это сообщение бота, поэтому используем user_id
    effective_uid = user_id or message.from_user.id
    status_msg = await message.answer("⌛ Получаю домашнее задание...")
    ns = await _get_ns_client(message, user_id=user_id)
    if not ns:
        cache = _load_netschool_cache(effective_uid)
        cached = (cache.get("homework") or {}).get("text")
        if cached:
            await message.reply("⚠️ Сервер недоступен, показываю сохранённые данные.\n\n" + cached)
        try:
            await status_msg.delete()
        except Exception:
            pass
        return
    try:
        today_d = datetime.now(dt_timezone(timedelta(hours=3))).date()
        min_target = min(target_dates)
        max_target = max(target_dates)
        weeks_back = max(0, (today_d - min_target).days // 7 + 1) if min_target < today_d else 0
        weeks_forward = max(2, (max_target - today_d).days // 7 + 1) if max_target > today_d else 2

        days = await _fetch_diary_days(ns, weeks_back=weeks_back, weeks_forward=weeks_forward)

        # Сначала запрашиваем вложения через API для всех заданий в целевые даты
        assign_meta: list[tuple[int, str]] = []  # (assignment.id, subject)
        for day in days:
            for lesson in day.lessons:
                for assignment in lesson.assignments:
                    deadline = assignment.deadline or day.day
                    if deadline not in target_dates:
                        continue
                    assign_meta.append((assignment.id, lesson.subject))

        attach_map: dict[int, list] = {}  # assignment.id → [{вложения}]

        async def _fetch_one_attach(aid: int, subj: str) -> None:
            try:
                attaches = await ns.attachments(aid)
                if attaches:
                    attach_map[aid] = [
                        {"id": att.id, "name": att.name, "subject": subj}
                        for att in attaches
                    ]
            except Exception:
                pass

        if assign_meta:
            await asyncio.gather(*[_fetch_one_attach(aid, subj) for aid, subj in assign_meta])

        # Теперь рендерим текст — знаем точное количество файлов для каждого задания
        text, all_attachments = _render_homework_text(
            days, target_dates, header, attach_map=attach_map
        )
        if not text:
            await message.reply("✅ Домашнее задание не найдено.")
            return

        keyboard = None
        if all_attachments:
            runtime.HOMEWORK_ATTACHMENTS_CACHE[effective_uid] = all_attachments
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📎 Скачать файлы", callback_data="dz_files")]
            ])
        await message.reply(text, reply_markup=keyboard)

        cache = _load_netschool_cache(effective_uid)
        cache["homework"] = {
            "text": text,
            "dates": [d.isoformat() for d in sorted(target_dates)],
            "updated_at": datetime.now().isoformat()
        }
        _save_netschool_cache(effective_uid, cache)
    finally:
        try:
            cached = getattr(ns, "_from_cache", False)
            if not cached:
                await _close_netschool_client(ns, do_logout=False)
        except Exception:
            pass
        try:
            await status_msg.delete()
        except Exception:
            pass

async def _send_schedule_for_dates(
    message: Message,
    target_dates: set[datetime.date],
    header: str,
    user_id: Optional[int] = None
) -> None:
    status_msg = await message.answer("⌛ Получаю расписание...")
    ns = await _get_ns_client(message, user_id=user_id)
    if not ns:
        cache = _load_netschool_cache(message.from_user.id)
        cached = (cache.get("schedule") or {}).get("text")
        if cached:
            await message.reply("⚠️ Сервер недоступен, показываю сохранённые данные.\n\n" + cached)
        try:
            await status_msg.delete()
        except Exception:
            pass
        return
    try:
        weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        weeks = {d - timedelta(days=d.weekday()) for d in target_dates}
        schedule_days = []
        for week_start in sorted(weeks):
            diary = await ns.diary(start=week_start)
            if getattr(diary, "schedule", None):
                schedule_days.extend([d for d in diary.schedule if d.lessons])

        days = [day for day in schedule_days if day.day in target_dates]
        days.sort(key=lambda d: d.day)
        if not days:
            await message.reply("✅ Нет расписания на выбранные даты.")
            return

        lines = [header]
        for day in days:
            weekday = weekday_names[day.day.weekday()]
            lines.append(f"\n📅 {weekday}, {day.day.strftime('%d.%m.%Y')}")
            lessons = list(day.lessons)
            lessons.sort(key=lambda l: (
                0 if l.start else 1,
                l.start or datetime.min.time(),
                l.number or 0
            ))
            for idx, lesson in enumerate(lessons, start=1):
                start = lesson.start.strftime("%H:%M") if lesson.start else ""
                end = lesson.end.strftime("%H:%M") if lesson.end else ""
                time_range = f"{start}-{end}".strip("-")
                room = f" (каб. {lesson.room})" if lesson.room else ""
                prefix = f"{idx}. "
                lines.append(f"{prefix}{time_range} {lesson.subject}{room}".strip())

        text = "\n".join(lines)
        await message.reply(text)

        cache = _load_netschool_cache(message.from_user.id)
        cache["schedule"] = {
            "text": text,
            "dates": [d.isoformat() for d in sorted(target_dates)],
            "updated_at": datetime.now().isoformat()
        }
        _save_netschool_cache(message.from_user.id, cache)
    finally:
        try:
            cached = getattr(ns, "_from_cache", False)
            if not cached:
                await _close_netschool_client(ns, do_logout=False)
        except Exception:
            pass
        try:
            await status_msg.delete()
        except Exception:
            pass

async def _send_mail_list(message: Message, user_id: Optional[int] = None):
    effective_user_id = user_id or message.from_user.id
    status_msg = await message.answer("⌛ Получаю почту...")
    ns = await _get_ns_client(message, user_id=effective_user_id)
    if not ns:
        try:
            await status_msg.delete()
        except Exception:
            pass
        return
    try:
        page = await ns.mail_list(folder="Inbox", page=1, page_size=10)
        entries = page.entries or []
        if not entries:
            await message.reply("✅ Входящих писем нет.")
            return
        lines = ["📬 Почта (входящие):"]
        keyboard_rows: list[list[InlineKeyboardButton]] = []
        for idx, entry in enumerate(entries, start=1):
            sent = entry.sent.strftime("%d.%m %H:%M")
            subject = entry.subject or "(без темы)"
            author = entry.author or "—"
            lines.append(f"{idx}. {sent} — {author} — {subject}")
            button_text = subject
            if len(button_text) > 25:
                button_text = button_text[:22] + "…"
            keyboard_rows.append([
                InlineKeyboardButton(
                    text=f"{idx}. {button_text}",
                    callback_data=f"mail_read:{entry.id}"
                )
            ])
        await message.reply(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        )
    finally:
        try:
            cached = getattr(ns, "_from_cache", False)
            if not cached:
                await _close_netschool_client(ns, do_logout=False)
        except Exception:
            pass
        try:
            await status_msg.delete()
        except Exception:
            pass

async def _send_grades_for_subject(
    target_message: Message,
    subject: str,
    days: list[Any],
    exact_subject: bool = False,
    q_start: Optional[datetime.date] = None
) -> None:
    quarter_start = q_start if q_start else _current_quarter_start()
    subjects, entries = _collect_grades(days, since_date=quarter_start)
    subject_title = subject
    if not exact_subject:
        matched, matches = _match_subject(subjects, subject)
        if not matched:
            if matches:
                await target_message.reply(
                    "❓ Уточните предмет. Подходят:\n" + "\n".join(f"• {s}" for s in matches)
                )
            else:
                await target_message.reply("❌ Предмет не найден. Проверьте название.")
            return
        subject_title = matched

    subject_norm = _normalize_subject(subject_title)
    filtered = [e for e in entries if _normalize_subject(e[0]) == subject_norm]
    if not filtered:
        await target_message.reply("✅ Оценок по предмету пока нет.")
        return

    text = _render_grades_text(subject_title, filtered)
    await target_message.reply(text)

    cache = _load_netschool_cache(target_message.from_user.id)
    grades_cache = cache.get("grades") or {}
    by_subject = grades_cache.get("by_subject") or {}
    by_subject[_normalize_subject(subject_title)] = text
    grades_cache.update({
        "by_subject": by_subject,
        "updated_at": datetime.now().isoformat()
    })
    cache["grades"] = grades_cache
    _save_netschool_cache(target_message.from_user.id, cache)

async def _load_period_entries(message: Message, user_id: int, start_date: datetime.date, end_date: datetime.date) -> tuple[list[dict[str, Any]], Optional[NetSchool]]:
    ns = await _get_ns_client(message, user_id=user_id)
    if not ns:
        return [], None
    user_data = get_netschool_user(user_id)
    include_subjects = get_user_subject_include_titles(user_data)
    days = await _fetch_days_for_period(ns, start_date, end_date)
    entries = _iter_grade_entries(days, start_date=start_date, end_date=end_date, include_subjects=include_subjects)
    return entries, ns

async def _render_netschool_control_center(target_message: Message, user_id: int, edit: bool = False, display_name: Optional[str] = None) -> None:
    user_data = get_netschool_user(user_id, display_name)
    token = _issue_netschool_miniapp_token(user_id)
    miniapp_url = _build_netschool_miniapp_url(token)
    text = _build_netschool_control_center_text(user_data, user_id)
    keyboard = _build_netschool_control_center_keyboard(user_data, miniapp_url=miniapp_url)
    if edit:
        try:
            await target_message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                raise
    else:
        await target_message.answer(text, parse_mode="HTML", reply_markup=keyboard)

async def _show_child_switch_dialog(message: Message, user_data: dict) -> None:
    students = _get_available_students(user_data)
    if len(students) < 2:
        await message.answer("ℹ️ В профиле найден только один ребёнок.")
        return
    selected_id = _safe_int(user_data.get("selected_student_id"))
    selected_name = ""
    for student in students:
        if selected_id is not None and student["id"] == selected_id:
            selected_name = student["name"]
            break
    if not selected_name:
        selected_name = user_data.get("student_name") or students[0]["name"]
    await message.answer(
        "👶 <b>Выберите ребёнка</b>\n\n"
        f"Сейчас: {html.escape(selected_name)}",
        parse_mode="HTML",
        reply_markup=_build_student_switch_keyboard(user_data),
    )

def _build_status_text(user_data: dict, user_id: int) -> str:
    enabled = "✅ включены" if user_data.get("enabled") else "🔕 выключены"
    interval = int(user_data.get("check_interval") or CHECK_INTERVAL)
    interval = _clamp_interval(interval)
    filters = ", ".join(user_data.get("filters", {}).get("exclude") or []) or "нет"
    subject_filters = ", ".join(user_data.get("subject_filters", {}).get("include") or []) or "все предметы"
    quiet_hours = format_user_quiet_hours(user_data)
    weekly_summary = "✅" if user_data.get("weekly_summary_enabled") else "❌"
    login_set = "✅ задан" if user_data.get("login") else "❌ не задан"
    password_set = "✅ задан" if user_data.get("password") else "❌ не задан"
    changes_enabled = "✅" if user_data.get("notify_changes", True) else "❌"
    deletes_enabled = "✅" if user_data.get("notify_deletes", True) else "❌"
    mail_enabled = "✅" if user_data.get("notify_mail", True) else "❌"
    known_count = None
    last_sync = user_data.get("last_sync_at")
    pending_bulk = user_data.get("pending_bulk") or []
    if user_id in runtime.netschool_user_notifiers:
        notifier = runtime.netschool_user_notifiers[user_id]
        if notifier and notifier.track_changes:
            known_count = len(notifier.known_grades)
    return (
        "📊 <b>Статус уведомлений</b>\n\n"
        f"• Уведомления: {enabled}\n"
        f"• Интервал: {interval // 60} мин (минимум 3, максимум 180)\n"
        f"• Логин: {login_set}\n"
        f"• Пароль: {password_set}\n"
        f"• Исключенные типы: {filters}\n"
        f"• Предметы: {subject_filters}\n"
        f"• Тихие часы: {quiet_hours}\n"
        f"• Недельная сводка: {weekly_summary}\n"
        f"• Известных оценок: {known_count if known_count is not None else '—'}\n"
        f"• Последняя синхронизация: {last_sync or '—'}\n"
        f"• Ожидают решения: {len(pending_bulk) if pending_bulk else '—'}\n"
        f"• Изменения: {changes_enabled}\n"
        f"• Удаления: {deletes_enabled}\n"
        f"• Почта: {mail_enabled}\n\n"
        "Для управления уведомлениями: /settings"
    )

def _format_bulk_summary(items: list[dict]) -> str:
    lines = []
    for item in items:
        assignment = item.get("assignment", {})
        mark_value = assignment.get('mark', {}).get('value', '')
        date_str = assignment.get('date', '')
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d.%m.%Y')
        except Exception:
            formatted_date = date_str
        lines.append(
            f"• {assignment.get('subjectName', '—')} — {assignment.get('assignmentType', assignment.get('assignmentName', '—'))}"
            f" — {formatted_date} — {mark_value}"
        )
    return "\n".join(lines)

def _format_events_summary(items: list[dict]) -> str:
    lines = []
    for item in items:
        kind = item.get("kind")
        assignment = item.get("assignment", {})
        date_str = assignment.get('date', '')
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d.%m.%Y')
        except Exception:
            formatted_date = date_str
        subject = assignment.get('subjectName', '—')
        typ = assignment.get('assignmentType', assignment.get('assignmentName', '—'))
        if kind == "change":
            old_mark = item.get("old_mark")
            new_mark = item.get("new_mark")
            lines.append(f"• Изм.: {subject} — {typ} — {formatted_date} — {old_mark}→{new_mark}")
        elif kind == "delete":
            old_mark = assignment.get('mark', {}).get('value', '')
            lines.append(f"• Удал.: {subject} — {typ} — {formatted_date} — {old_mark}")
    return "\n".join(lines)

def _format_homework_summary(items: list[dict]) -> str:
    lines = []
    for item in items:
        homework = item.get("homework", {})
        date_str = homework.get("date", "")
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d.%m.%Y')
        except Exception:
            formatted_date = date_str
        text = str(homework.get("text") or "Не указана").strip() or "Не указана"
        if len(text) > 80:
            text = text[:77] + "..."
        seen_time = datetime.now().strftime('%d.%m %H:%M')
        lines.append(
            f"• <b>{homework.get('subjectName', '—')}</b> | Сдать: {formatted_date}\n"
            f"  └ <i>{html.escape(text)}</i>"
        )
    return "\n".join(lines) + f"\n\n🕒 <i>Замечено: {datetime.now().strftime('%d.%m.%Y в %H:%M')}</i>"

async def _proceed_to_auth(msg_or_callback, user_id: int, user_data: dict, url: str, school: str):
    """Общая логика: определяем методы входа для school/url и показываем выбор."""
    loading_msg = await msg_or_callback.answer("⏳ Проверяю доступные способы входа...")
    login_methods = None
    try:
        from netschoolpy import get_login_methods
        login_methods = await get_login_methods(url, timeout=10)
    except Exception as e:
        logger.warning(f"Не удалось получить способы входа для {url}: {e}")
    try:
        await loading_msg.delete()
    except Exception:
        pass

    school_display = html.escape(school)
    if login_methods and login_methods.esia_main and not login_methods.password:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏛 Госуслуги (логин/пароль)", callback_data="ns_auth_method:esia")],
            [InlineKeyboardButton(text="📱 Госуслуги (QR-код)", callback_data="ns_auth_method:esia_qr")],
            [InlineKeyboardButton(text="🌍 Сменить регион/школу", callback_data="ns_choose_region")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")],
        ])
        set_netschool_user_state(user_id, "await_auth_method")
        await msg_or_callback.answer(
            f"🔑 Школа: <b>{school_display}</b>\n"
            "Вход только через Госуслуги.\n\n"
            "Выберите способ:",
            parse_mode="HTML",
            reply_markup=kb
        )
    elif login_methods and login_methods.esia and login_methods.password:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Логин и пароль журнала", callback_data="ns_auth_method:password")],
            [InlineKeyboardButton(text="🏛 Госуслуги (логин/пароль)", callback_data="ns_auth_method:esia")],
            [InlineKeyboardButton(text="📱 Госуслуги (QR-код)", callback_data="ns_auth_method:esia_qr")],
            [InlineKeyboardButton(text="🌍 Сменить регион/школу", callback_data="ns_choose_region")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")],
        ])
        set_netschool_user_state(user_id, "await_auth_method")
        await msg_or_callback.answer(
            f"🔑 Школа: <b>{school_display}</b>\n\n"
            "Выберите способ входа:",
            parse_mode="HTML",
            reply_markup=kb
        )
    else:
        user_data["login_type"] = "password"
        save_netschool_users()
        set_netschool_user_state(user_id, "await_login")
        await msg_or_callback.answer(
            f"🔑 Школа: <b>{school_display}</b>\n"
            "Отправьте логин одним сообщением.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🌍 Сменить регион/школу", callback_data="ns_choose_region")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")],
            ])
        )

async def _start_qr_login(msg, user_id: int, user_data: dict):
    """Запуск QR-входа через Госуслуги."""
    user_url = _get_user_ns_url(user_data)
    user_school = _get_user_ns_school(user_data)
    if not user_url:
        await msg.answer("❌ Не указан URL журнала. Начните с /login.")
        return

    user_data["login_type"] = "esia_qr"
    save_netschool_users()
    set_netschool_user_state(user_id, "await_qr_scan")

    status_msg = await msg.answer(
        "📱 Генерирую QR-код для входа через Госуслуги...\n"
        "Это может занять несколько секунд."
    )

    qr_photo_msg = None

    async def qr_callback(qr_content: str):
        nonlocal qr_photo_msg
        try:
            import qrcode
            qr_img = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr_img.add_data(qr_content)
            qr_img.make(fit=True)
            img = qr_img.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            photo = BufferedInputFile(buf.read(), filename="gosuslugi_qr.png")
            qr_photo_msg = await msg.answer_photo(
                photo=photo,
                caption=(
                    "📱 Отсканируйте QR-код в приложении «Госуслуги».\n\n"
                    "⏳ Ожидаю подтверждения..."
                ),
            )
        except Exception as e:
            logger.warning(f"Не удалось создать QR-картинку: {e}")
            await msg.answer(
                f"📱 Откройте ссылку в приложении «Госуслуги»:\n\n"
                f"<code>{html.escape(qr_content)}</code>\n\n"
                "⏳ Ожидаю подтверждения...",
                parse_mode="HTML",
            )

    ns = None
    try:
        from netschoolpy import NetSchool
        ns = _make_netschool(user_url)
        await ns.login_via_gosuslugi_qr(
            qr_callback=qr_callback,
            qr_timeout=120,
            school=user_school,
            timeout=30,
        )
        # Успешный вход
        try:
            await status_msg.delete()
        except Exception:
            pass
        user_data["login"] = "gosuslugi_qr"
        user_data["password"] = ""
        user_data["login_type"] = "esia_qr"
        user_data["enabled"] = True
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        set_netschool_user_state(user_id, "")
        await msg.answer(
            "✅ Вход через Госуслуги (QR) выполнен успешно!\n"
            "Уведомления об оценках включены.\n\n"
            "Открывайте Центр или главное меню для дальнейшей работы.",
            reply_markup=_build_netschool_main_menu(user_data)
        )
        await _close_netschool_session_for_user(user_id, clear_saved=True)
        _ns_clients[user_id] = ns
        ns = None  # не закрываем — сохранили
        await start_user_grade_task(user_id, runtime.bot, runtime.log_bot, TG_ADMIN_ID)
    except asyncio.TimeoutError:
        try:
            await status_msg.delete()
        except Exception:
            pass
        set_netschool_user_state(user_id, "")
        await msg.answer(
            "⏰ Время ожидания QR-кода истекло.\n"
            "Попробуйте ещё раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Повторить QR", callback_data="ns_qr_retry")],
                [InlineKeyboardButton(text="🏛 Логин/пароль Госуслуг", callback_data="ns_auth_method:esia")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")],
            ])
        )
    except Exception as e:
        try:
            await status_msg.delete()
        except Exception:
            pass
        set_netschool_user_state(user_id, "")
        err_text = str(e)
        err_lower = err_text.lower()
        err_class = _classify_login_error(e)
        logger.warning(f"QR login error [{err_class}]: {err_text[:500]}")
        # Сессия ESIA истекла / QR протух
        if "сессия истекла" in err_lower or "session" in err_lower or "expired" in err_lower or "outdated" in err_lower:
            await msg.answer(
                "⏰ QR-сессия истекла.\n"
                "Попробуйте сгенерировать новый QR-код.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Новый QR", callback_data="ns_qr_retry")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")],
                ])
            )
        elif err_class == "esia":
            await msg.answer(
                "❌ Сервер Госуслуг (ЕСИА) недоступен.\n"
                "Попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Повторить", callback_data="ns_qr_retry")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")],
                ])
            )
        elif err_class == "server":
            await msg.answer(
                "❌ Сервер журнала недоступен. Попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Повторить", callback_data="ns_qr_retry")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")],
                ])
            )
        else:
            safe_err = html.escape(err_text[:300])
            await msg.answer(
                f"❌ Ошибка входа через QR:\n<code>{safe_err}</code>\n\n"
                "Попробуйте другой способ.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Повторить QR", callback_data="ns_qr_retry")],
                    [InlineKeyboardButton(text="🏛 Логин/пароль Госуслуг", callback_data="ns_auth_method:esia")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")],
                ])
            )
    finally:
        if ns is not None:
            try:
                await _close_netschool_client(ns, do_logout=False)
            except Exception:
                pass

