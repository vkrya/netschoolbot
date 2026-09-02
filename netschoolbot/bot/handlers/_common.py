"""Общий набор импортов для модулей обработчиков.

Модули хендлеров делают `from ._common import *` — так перенесённый из
монолита код работает без правки каждого обращения.
"""

import asyncio
import html
import io
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, Set

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from netschoolpy import NetSchool
import netschoolpy.exceptions as netschoolpy_exceptions

from ... import config
from ...config import (
    ADMIN_ID as TG_ADMIN_ID,
    BOT_TOKEN as NETSCHOOL_BOT_TOKEN,
    CHECK_INTERVAL,
    MINIAPP_ACCESS_REQUEST_TTL as NETSCHOOL_MINIAPP_ACCESS_REQUEST_TTL,
    MINIAPP_BASE_URL as NETSCHOOL_MINIAPP_BASE_URL,
    MAX_INTERVAL as NETSCHOOL_MAX_INTERVAL,
    MIN_INTERVAL as NETSCHOOL_MIN_INTERVAL,
    NETSCHOOL_MINIAPP_GALLERY_DIR as PWA_GALLERY_DIR,
    NETSCHOOL_MINIAPP_ICONS_DIR,
    NETSCHOOL_USERS_DIR,
)
from ...netschool import client as ns_client
from ...netschool.client import (
    NETSCHOOL_SESSION_CACHE,
    NETSCHOOL_SESSION_TTL,
    _apply_selected_student_to_client,
    _classify_login_error,
    _close_all_netschool_sessions,
    _close_netschool_client,
    _close_netschool_session,
    _close_netschool_session_for_user,
    _fetch_days_for_period,
    _fetch_diary_days,
    _fetch_student_name,
    _make_netschool,
    _netschool_session_is_alive,
    _netschool_session_path,
    _ns_clients,
    _save_netschool_session,
    _sync_user_students_from_ns,
    _try_restore_netschool_session,
    esia_otp_futures,
    is_esia_connection_error,
    is_netschool_auth_error,
    is_server_unavailable_error,
)
from ...netschool.grades import (
    _build_mystats_text,
    _build_profile_text,
    _build_weeksummary_text,
    _collect_grades,
    _iter_grade_entries,
    _load_netschool_cache,
    _refresh_user_cache_from_days,
    _render_grades_text,
    _render_homework_text,
    _render_schedule_text,
    _save_netschool_cache,
)
from ... import storage
from ...storage import (
    GRADE_FEEDBACK_LABELS,
    GRADE_FEEDBACK_OPTIONS,
    _build_netschool_miniapp_url,
    _clamp_interval,
    _cleanup_expired_netschool_miniapp_access_requests,
    _count_grade_feedback_votes,
    _default_exclude_titles,
    _delete_pwa_gallery_icon,
    _ensure_grade_feedback_entry,
    _format_netschool_pwa_access_status,
    _get_available_students,
    _get_netschool_user_state,
    _get_user_ns_school,
    _get_user_ns_url,
    _issue_netschool_miniapp_token,
    _issue_netschool_pwa_token,
    _issue_netschool_session_code,
    _load_netschool_miniapp_access_requests,
    _load_netschool_miniapp_tokens,
    _load_pwa_gallery,
    _normalize_netschool_school_value,
    _pwa_gallery_image_path,
    _revoke_pwa_icon_access,
    _save_grade_feedback_store,
    _save_netschool_miniapp_access_requests,
    _save_netschool_miniapp_tokens,
    _save_pwa_gallery,
    _send_netschool_web_push,
    format_user_quiet_hours,
    get_netschool_user,
    get_user_display_name,
    get_user_exclude_titles,
    get_user_quiet_hours,
    get_user_student_name,
    get_user_subject_include_titles,
    is_subject_allowed_for_user,
    is_user_quiet_hours_now,
    load_netschool_users,
    save_netschool_users,
    set_netschool_user_state,
)
from ...utils import (
    _clean_assignment_content,
    _current_quarter_start,
    _extract_mark_value,
    _file_count_label,
    _format_assignment_title,
    _format_date_label,
    _format_timedelta,
    _mark_to_int,
    _match_subject,
    _msk_tz,
    _next_three_days,
    _normalize_subject,
    _normalize_title,
    _parse_date_input,
    _parse_hhmm,
    _parse_mark_value,
    _quarter_start_for_user,
    _safe_int,
    _split_message,
    now_msk,
    parse_interval_input,
)
from .. import runtime
from ..esia import _make_esia_mfa_callback
from ..helpers import (
    _build_status_text,
    _ensure_student_selected,
    _format_bulk_summary,
    _format_events_summary,
    _format_homework_summary,
    _get_ns_client,
    _load_period_entries,
    _proceed_to_auth,
    _render_netschool_control_center,
    _send_grades_for_subject,
    _send_homework_for_dates,
    _send_mail_list,
    _send_pwa_gallery_previews,
    _send_schedule_for_dates,
    _show_child_switch_dialog,
    _start_qr_login,
)
from ..keyboards import (
    _build_calendar_keyboard,
    _build_date_choice_keyboard,
    _build_grade_feedback_keyboard,
    _build_grades_subjects_keyboard,
    _build_interval_presets_keyboard,
    _build_netschool_control_center_keyboard,
    _build_netschool_control_center_text,
    _build_netschool_main_menu,
    _build_pwa_gallery_admin_keyboard,
    _build_pwa_gallery_preview_keyboard,
    _build_quiet_hours_keyboard,
    _build_region_keyboard,
    _build_reply_keyboard,
    _build_settings_keyboard,
    _build_settings_text,
    _build_student_switch_keyboard,
    _build_subject_filter_keyboard,
    _insert_child_switch_row,
    _kb_back_cancel,
    _kb_back_to_login,
    _kb_bulk_choice,
    _kb_cancel_action,
    _kb_events_choice,
    _kb_homework_choice,
)
from ..tasks import (
    refresh_user_grade_task,
    start_all_user_grade_tasks,
    start_login_retry_task,
    start_user_grade_task,
    stop_login_retry_task,
    stop_user_grade_task,
)

logger = logging.getLogger("netschoolbot")

__all__ = [name for name in dir() if not name.startswith("__")]
