"""Все inline/reply-клавиатуры бота и связанные с ними тексты."""

import calendar
import datetime
import html
import logging
from datetime import timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, Optional

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from .. import config
from ..config import CHECK_INTERVAL
from ..storage import (
    GRADE_FEEDBACK_OPTIONS,
    _clamp_interval,
    _count_grade_feedback_votes,
    _get_available_students,
    _get_user_ns_school,
    _get_user_ns_url,
    _load_grade_feedback_store,
    format_user_quiet_hours,
    get_user_student_name,
)
from ..utils import _format_date_label, _normalize_subject, _safe_int
from . import runtime

logger = logging.getLogger("netschoolbot")


def _build_grade_feedback_keyboard(feedback_id: str, store: Optional[Dict[str, Any]] = None) -> InlineKeyboardMarkup:
    source = store or _load_grade_feedback_store()
    entry = source.get("entries", {}).get(feedback_id) or {"votes": {}}
    counts = _count_grade_feedback_votes(entry)
    rows = [
        [
            InlineKeyboardButton(text=f"У меня 5 ({counts['5']})", callback_data=f"ns_gradevote:{feedback_id}:5"),
            InlineKeyboardButton(text=f"У меня 4 ({counts['4']})", callback_data=f"ns_gradevote:{feedback_id}:4"),
        ],
        [
            InlineKeyboardButton(text=f"У меня 3 ({counts['3']})", callback_data=f"ns_gradevote:{feedback_id}:3"),
            InlineKeyboardButton(text=f"У меня 2 ({counts['2']})", callback_data=f"ns_gradevote:{feedback_id}:2"),
        ],
        [
            InlineKeyboardButton(text=f"Не писал/не выставили ({counts['none']})", callback_data=f"ns_gradevote:{feedback_id}:none"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _build_pwa_gallery_admin_keyboard(icons: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for icon in icons[-20:]:
        label = f"#{str(icon.get('id') or '')[:12]} (user {icon.get('user_id', '?')})"
        rows.append([InlineKeyboardButton(text=f"🗑 {label}", callback_data=f"ns_gal_del:{icon.get('id')}")])
    rows.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="ns_gal_close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _build_pwa_gallery_preview_keyboard(icon: dict[str, Any], *, mode: str = "all") -> InlineKeyboardMarkup:
    gallery_id = str(icon.get("id") or "")
    owner_id = int(icon.get("user_id") or 0)
    rows: list[list[InlineKeyboardButton]] = []
    if mode == "revoke":
        rows.append([InlineKeyboardButton(text="⛔ Отозвать токены владельца", callback_data=f"ns_gal_revoke:{owner_id}")])
    else:
        rows.append([
            InlineKeyboardButton(text="🗑 Удалить из галереи", callback_data=f"ns_gal_del:{gallery_id}"),
            InlineKeyboardButton(text="⛔ Отозвать токены", callback_data=f"ns_gal_revoke:{owner_id}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _build_netschool_control_center_text(user_data: Dict[str, Any], user_id: int) -> str:
    interval = _clamp_interval(int(user_data.get("check_interval") or CHECK_INTERVAL))
    type_filters = ", ".join(user_data.get("filters", {}).get("exclude") or []) or "нет"
    subject_filters = ", ".join(user_data.get("subject_filters", {}).get("include") or []) or "все предметы"
    known_count = None
    if user_id in runtime.netschool_user_notifiers:
        notifier = runtime.netschool_user_notifiers[user_id]
        if notifier and notifier.track_changes:
            known_count = len(notifier.known_grades)
    return (
        "🪟 <b>Центр NetSchool</b>\n\n"
        f"👤 <b>Профиль:</b> {html.escape(get_user_student_name(user_id) or user_data.get('display_name') or f'ID {user_id}')}\n"
        f"🏫 <b>Школа:</b> {html.escape(str(_get_user_ns_school(user_data) or '—'))}\n"
        f"🌐 <b>URL:</b> {html.escape(str(_get_user_ns_url(user_data) or '—'))}\n\n"
        f"🔔 <b>Оценки:</b> {'включены ✅' if user_data.get('enabled') else 'выключены 🔕'}\n"
        f"📬 <b>Почта:</b> {'включена ✅' if user_data.get('notify_mail', True) else 'выключена 🔕'}\n"
        f"🔄 <b>Изменения:</b> {'включены ✅' if user_data.get('notify_changes', True) else 'выключены 🔕'}\n"
        f"🗑 <b>Удаления:</b> {'включены ✅' if user_data.get('notify_deletes', True) else 'выключены 🔕'}\n"
        f"📨 <b>Автосводка:</b> {'включена ✅' if user_data.get('weekly_summary_enabled') else 'выключена 🔕'}\n"
        f"⏱ <b>Интервал:</b> {interval // 60} мин\n"
        f"🌙 <b>Тихие часы:</b> {format_user_quiet_hours(user_data)}\n"
        f"📘 <b>Предметы:</b> {html.escape(subject_filters)}\n"
        f"🧰 <b>Фильтр типов:</b> {html.escape(type_filters)}\n"
        f"📊 <b>Известных оценок:</b> {known_count if known_count is not None else '—'}\n"
        f"🕒 <b>Последняя синхронизация:</b> {html.escape(str(user_data.get('last_sync_at') or '—'))}"
    )

def _build_netschool_control_center_keyboard(user_data: Dict[str, Any], miniapp_url: Optional[str] = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="ns_panel:refresh"),
        ],
        [
            InlineKeyboardButton(text=("🔕 Оценки" if user_data.get("enabled") else "🔔 Оценки"), callback_data="ns_panel:toggle:enabled"),
            InlineKeyboardButton(text=("📬 Почта ✅" if user_data.get("notify_mail", True) else "📬 Почта 🔕"), callback_data="ns_panel:toggle:mail"),
        ],
        [
            InlineKeyboardButton(text=("🔄 Изм. ✅" if user_data.get("notify_changes", True) else "🔄 Изм. 🔕"), callback_data="ns_panel:toggle:changes"),
            InlineKeyboardButton(text=("🗑 Удал. ✅" if user_data.get("notify_deletes", True) else "🗑 Удал. 🔕"), callback_data="ns_panel:toggle:deletes"),
        ],
        [
            InlineKeyboardButton(text=("📨 Сводка ✅" if user_data.get("weekly_summary_enabled") else "📨 Сводка 🔕"), callback_data="ns_panel:toggle:weekly"),
            InlineKeyboardButton(text="⏱ Интервал", callback_data="ns_menu:interval"),
        ],
        [
            InlineKeyboardButton(text="📘 Предметы", callback_data="ns_menu:subjectfilter"),
            InlineKeyboardButton(text="🌙 Тихие часы", callback_data="ns_menu:quiethours"),
        ],
    ]
    if miniapp_url:
        if miniapp_url.startswith("https://"):
            rows.append([InlineKeyboardButton(text="📱 Мини-приложение", web_app=WebAppInfo(url=miniapp_url))])
        else:
            rows.append([InlineKeyboardButton(text="📱 Мини-приложение", url=miniapp_url)])
    rows.append([InlineKeyboardButton(text="🔗 PWA-ссылка", callback_data="ns_menu:pwalink")])
    rows.append([InlineKeyboardButton(text="↩️ Главное меню", callback_data="ns_panel:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _build_date_choice_keyboard(prefix: str, dates: list[datetime.date]) -> InlineKeyboardMarkup:
    rows = []
    row: list[InlineKeyboardButton] = []
    for day in dates:
        row.append(InlineKeyboardButton(text=_format_date_label(day), callback_data=f"{prefix}:{day.isoformat()}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    # Кнопка «Календарь» вместо текстового ввода
    today = datetime.now(dt_timezone(timedelta(hours=3))).date()
    rows.append([InlineKeyboardButton(text="🗓 Календарь", callback_data=f"cal:{prefix}:{today.year}:{today.month}")])
    rows.append([InlineKeyboardButton(text="↩️ Главное меню", callback_data="ns_panel:menu")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="ns_back_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _build_calendar_keyboard(prefix: str, year: int, month: int) -> InlineKeyboardMarkup:
    """Строит inline-клавиатуру-календарь для выбора даты."""
    import calendar
    month_names = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                   "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    rows: list[list[InlineKeyboardButton]] = []
    # Заголовок: < Март 2026 >
    rows.append([
        InlineKeyboardButton(text="◀️", callback_data=f"cal_nav:{prefix}:{year}:{month}:-1"),
        InlineKeyboardButton(text=f"{month_names[month]} {year}", callback_data="cal_ignore"),
        InlineKeyboardButton(text="▶️", callback_data=f"cal_nav:{prefix}:{year}:{month}:1"),
    ])
    # Дни недели
    rows.append([
        InlineKeyboardButton(text=d, callback_data="cal_ignore")
        for d in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    ])
    # Дни месяца
    cal = calendar.monthcalendar(year, month)
    today = datetime.now(dt_timezone(timedelta(hours=3))).date()
    for week in cal:
        row: list[InlineKeyboardButton] = []
        for d in week:
            if d == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="cal_ignore"))
            else:
                dt = datetime(year, month, d).date()
                label = f"·{d}·" if dt == today else str(d)
                row.append(InlineKeyboardButton(
                    text=label,
                    callback_data=f"{prefix}:{dt.isoformat()}"
                ))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="↩️ Главное меню", callback_data="ns_panel:menu")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cal_close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _build_grades_subjects_keyboard(subjects: list[str], page: int = 0) -> InlineKeyboardMarkup:
    start = page * runtime.GRADES_SUBJECTS_PAGE_SIZE
    end = start + runtime.GRADES_SUBJECTS_PAGE_SIZE
    page_items = subjects[start:end]
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, subject in enumerate(page_items, start=start):
        row.append(InlineKeyboardButton(text=subject, callback_data=f"grades_subj:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav: list[InlineKeyboardButton] = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"grades_page:{page - 1}"))
    if end < len(subjects):
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"grades_page:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="↩️ Главное меню", callback_data="ns_panel:menu")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="ns_back_cancel")])

    return InlineKeyboardMarkup(inline_keyboard=rows)

def _kb_back_to_login() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_login")]
    ])

def _kb_back_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")]
    ])

def _kb_cancel_action(callback_data: str = "ns_back_cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=callback_data)]
    ])

def _build_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Открыть дневник"), KeyboardButton(text="⚙️ Меню")],
        ],
        resize_keyboard=True,
        persistent=True
    )

def _build_netschool_main_menu(user_data: dict) -> InlineKeyboardMarkup:
    enabled = bool(user_data.get("enabled"))
    has_credentials = bool(user_data.get("login") and user_data.get("password"))
    auth_text = "🔄 Перезайти" if has_credentials else "🔐 Войти"
    auth_action = "relogin" if has_credentials else "login"
    notif_text = "🔕 Выключить уведомления" if enabled else "🔔 Включить уведомления"
    notif_action = "off" if enabled else "on"
    rows = [
        [
            InlineKeyboardButton(text="📱 Открыть дневник", callback_data="ns_menu:miniapp"),
        ],
        [
            InlineKeyboardButton(text="📝 ДЗ", callback_data="ns_menu:homework"),
            InlineKeyboardButton(text="📚 Оценки", callback_data="ns_menu:grades"),
        ],
        [
            InlineKeyboardButton(text="🔗 PWA-ссылка", callback_data="ns_menu:pwalink"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="ns_menu:settings"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="ns_menu:profile"),
        ],
    ]

    role_row = []
    if user_data.get("role") == "parent":
        role_row.append(InlineKeyboardButton(text="👨‍👩‍👧‍👦 Ученики", callback_data="ns_menu:students"))
    role_row.append(InlineKeyboardButton(text="🐛 Баг-репорт", callback_data="ns_menu:bugreport"))
    rows.append(role_row)

    rows.extend([
        [
            InlineKeyboardButton(text=auth_text, callback_data=f"ns_menu:{auth_action}"),
            InlineKeyboardButton(text=notif_text, callback_data=f"ns_menu:{notif_action}"),
        ],
        [
            InlineKeyboardButton(text="🪟 Центр", callback_data="ns_menu:hub"),
        ],
    ])
    rows = _insert_child_switch_row(rows, user_data, before_callback="ns_menu:bugreport")
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _build_student_switch_keyboard(user_data: dict) -> InlineKeyboardMarkup:
    students = _get_available_students(user_data)
    selected_id = _safe_int(user_data.get("selected_student_id"))
    rows: list[list[InlineKeyboardButton]] = []
    for student in students:
        mark = "✅ " if selected_id is not None and student["id"] == selected_id else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{mark}{student['name']}",
                callback_data=f"ns_child:{student['id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text="↩️ Главное меню", callback_data="ns_panel:menu")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="ns_back_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _insert_child_switch_row(
    rows: list[list[InlineKeyboardButton]],
    user_data: dict,
    *,
    before_callback: str | None = None,
) -> list[list[InlineKeyboardButton]]:
    if len(_get_available_students(user_data)) < 2:
        return rows
    child_row = [InlineKeyboardButton(text="👶 Ребёнок", callback_data="ns_menu:child")]
    if not before_callback:
        rows.append(child_row)
        return rows
    insert_idx = None
    for idx, row in enumerate(rows):
        if any(getattr(btn, "callback_data", "") == before_callback for btn in row):
            insert_idx = idx
            break
    if insert_idx is None:
        rows.append(child_row)
    else:
        rows.insert(insert_idx, child_row)
    return rows

def _build_quiet_hours_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="23:00 - 07:00", callback_data="ns_qh:23:00|07:00"),
            InlineKeyboardButton(text="22:00 - 07:00", callback_data="ns_qh:22:00|07:00"),
        ],
        [
            InlineKeyboardButton(text="00:00 - 08:00", callback_data="ns_qh:00:00|08:00"),
            InlineKeyboardButton(text="Выключить", callback_data="ns_qh:off"),
        ],
        [InlineKeyboardButton(text="↩️ Центр", callback_data="ns_menu:hub")],
        [InlineKeyboardButton(text="↩️ Главное меню", callback_data="ns_panel:menu")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="ns_back_cancel")],
    ])

def _build_subject_filter_keyboard(subjects: list[str], selected: set[str], page: int = 0) -> InlineKeyboardMarkup:
    page_size = 8
    start = page * page_size
    end = start + page_size
    page_subjects = subjects[start:end]
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, subject in enumerate(page_subjects, start=start):
        mark = "✅ " if _normalize_subject(subject) in selected else ""
        row.append(InlineKeyboardButton(text=f"{mark}{subject}", callback_data=f"ns_sf_toggle:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav: list[InlineKeyboardButton] = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"ns_sf_page:{page - 1}"))
    if end < len(subjects):
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"ns_sf_page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="♻️ Сбросить", callback_data="ns_sf_reset")])
    rows.append([InlineKeyboardButton(text="↩️ Центр", callback_data="ns_menu:hub")])
    rows.append([InlineKeyboardButton(text="↩️ Главное меню", callback_data="ns_panel:menu")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="ns_back_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _build_interval_presets_keyboard() -> InlineKeyboardMarkup:
    presets = [
        ("3 мин", 180),
        ("5 мин", 300),
        ("10 мин", 600),
        ("15 мин", 900),
        ("30 мин", 1800),
        ("1 час", 3600),
    ]
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for label, seconds in presets:
        row.append(InlineKeyboardButton(text=label, callback_data=f"ns_interval:{seconds}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="↩️ Центр", callback_data="ns_menu:hub")])
    rows.append([InlineKeyboardButton(text="↩️ Главное меню", callback_data="ns_panel:menu")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="ns_back_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _build_region_keyboard(page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    from netschoolpy import list_regions
    regions = list_regions()
    start = page * page_size
    end = start + page_size
    page_items = regions[start:end]
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, name in enumerate(page_items, start=start):
        row.append(InlineKeyboardButton(text=name, callback_data=f"ns_region:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav: list[InlineKeyboardButton] = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"ns_region_page:{page - 1}"))
    if end < len(regions):
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"ns_region_page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🌐 Ввести URL вручную", callback_data="ns_region:custom_url")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="ns_back_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _kb_bulk_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Списком", callback_data="ns_bulk_summary")],
        [InlineKeyboardButton(text="❌ Не отправлять", callback_data="ns_bulk_skip")]
    ])

def _kb_events_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить все", callback_data="ns_events_send_all"),
            InlineKeyboardButton(text="📝 Списком", callback_data="ns_events_summary")
        ],
        [InlineKeyboardButton(text="❌ Не отправлять", callback_data="ns_events_skip")]
    ])

def _kb_homework_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Списком", callback_data="ns_homework_summary")],
        [InlineKeyboardButton(text="❌ Не отправлять", callback_data="ns_homework_skip")]
    ])

def _build_settings_keyboard(user_data: dict) -> InlineKeyboardMarkup:
    """Строит клавиатуру настроек уведомлений с кнопками-переключателями."""
    def _tog(flag: bool) -> str:
        return "✅" if flag else "🔕"

    enabled = bool(user_data.get("enabled"))
    changes = bool(user_data.get("notify_changes", True))
    deletes = bool(user_data.get("notify_deletes", True))
    mail = bool(user_data.get("notify_mail", True))
    weekly = bool(user_data.get("weekly_summary_enabled"))

    rows = [
        [
            InlineKeyboardButton(
                text=f"🔔 Уведомления {_tog(enabled)}",
                callback_data="ns_toggle:enabled"
            ),
            InlineKeyboardButton(
                text=f"📨 Автосводка {_tog(weekly)}",
                callback_data="ns_toggle:weekly"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"📬 Почта {_tog(mail)}",
                callback_data="ns_toggle:mail"
            ),
            InlineKeyboardButton(
                text=f"🔄 Изменения {_tog(changes)}",
                callback_data="ns_toggle:changes"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"🗑 Удаления {_tog(deletes)}",
                callback_data="ns_toggle:deletes"
            ),
            InlineKeyboardButton(
                text="🌙 Тихие часы",
                callback_data="ns_menu:quiethours"
            ),
        ],
        [
            InlineKeyboardButton(text="📘 Предметы", callback_data="ns_menu:subjectfilter"),
            InlineKeyboardButton(text="⏱ Интервал", callback_data="ns_menu:interval"),
        ],
        [
            InlineKeyboardButton(text="Баг-репорт", callback_data="ns_menu:bugreport"),
        ],
        [InlineKeyboardButton(text="↩️ Главное меню", callback_data="ns_panel:menu")],
    ]
    rows = _insert_child_switch_row(rows, user_data, before_callback="ns_menu:bugreport")
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _build_settings_text(user_data: dict) -> str:
    def _lbl(flag: bool) -> str:
        return "включено ✅" if flag else "выключено 🔕"
    enabled = bool(user_data.get("enabled"))
    changes = bool(user_data.get("notify_changes", True))
    deletes = bool(user_data.get("notify_deletes", True))
    mail = bool(user_data.get("notify_mail", True))
    weekly = bool(user_data.get("weekly_summary_enabled"))
    interval = _clamp_interval(int(user_data.get("check_interval") or CHECK_INTERVAL))
    return (
        "⚙️ <b>Настройки уведомлений</b>\n\n"
        f"🔔 Уведомления оценок: {_lbl(enabled)}\n"
        f"🔄 Изменения оценок: {_lbl(changes)}\n"
        f"🗑 Удаление оценок: {_lbl(deletes)}\n"
        f"📬 Новые письма: {_lbl(mail)}\n"
        f"📨 Недельная сводка: {_lbl(weekly)}\n\n"
        f"⏱ Интервал проверки: {interval // 60} мин\n\n"
        "<i>Быстрые переключатели ниже. Для полного обзора удобнее открыть Центр. Команды:\n"
        "/on | /off — вкл/выкл оценки\n"
        "/interval 10m — изменить интервал\n"
        "/subjectfilter add Алгебра — фильтр по предметам\n"
        "/quiethours 23:00 07:00 — тихие часы\n"
        "/weekly_on | /weekly_off — недельная сводка\n"
        "/changes_on | /changes_off — изменения\n"
        "/deletes_on | /deletes_off — удаления\n"
        "/mail_on | /mail_off — письма</i>"
    )

