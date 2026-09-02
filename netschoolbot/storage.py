"""Хранилище данных бота: пользователи, токены миниприложения, коды входа,
запросы доступа, галерея PWA-иконок, голоса за оценки.

Все функции сохранили имена из старого монолита, чтобы перенесённые
обработчики работали без правок.
"""

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set
from urllib.parse import urlencode

from . import config
from .config import (
    CHECK_INTERVAL,
    GRADE_FEEDBACK_FILE as NETSCHOOL_GRADE_FEEDBACK_FILE,
    GALLERY_INDEX_FILE as PWA_GALLERY_INDEX_FILE,
    MAX_INTERVAL as NETSCHOOL_MAX_INTERVAL,
    MINIAPP_ACCESS_REQUESTS_FILE as NETSCHOOL_MINIAPP_ACCESS_REQUESTS_FILE,
    MINIAPP_ARCHIVE_TTL as NETSCHOOL_MINIAPP_ARCHIVE_TTL,
    MINIAPP_BASE_URL as NETSCHOOL_MINIAPP_BASE_URL,
    MINIAPP_TOKEN_TTL as NETSCHOOL_MINIAPP_TOKEN_TTL,
    MIN_INTERVAL as NETSCHOOL_MIN_INTERVAL,
    NETSCHOOL_MINIAPP_GALLERY_DIR as PWA_GALLERY_DIR,
    NETSCHOOL_MINIAPP_ICONS_DIR,
    NETSCHOOL_USERS_DIR,
    SESSION_CODES_FILE as NETSCHOOL_SESSION_CODES_FILE,
    MINIAPP_TOKENS_FILE as NETSCHOOL_MINIAPP_TOKENS_FILE,
    USERS_FILE as NETSCHOOL_USERS_FILE,
)
from .utils import _normalize_subject, _normalize_title, _parse_hhmm, _safe_int
from .webpush import send_user_push

logger = logging.getLogger("netschoolbot")

netschool_users: Dict[str, Any] = {"users": {}}
NETSCHOOL_USERS_FILE_MTIME: float = 0.0

GRADE_FEEDBACK_OPTIONS: list[tuple[str, str]] = [
    ("5", "У меня 5"),
    ("4", "У меня 4"),
    ("3", "У меня 3"),
    ("2", "У меня 2"),
    ("none", "Не писал/не выставили"),
]
GRADE_FEEDBACK_LABELS: Dict[str, str] = dict(GRADE_FEEDBACK_OPTIONS)


def _default_exclude_titles() -> list[str]:
    return []

def _default_exclude_titles_common() -> list[str]:
    return ["домашнее задание", "ответ на уроке"]

def load_netschool_users() -> None:
    """Загружает настройки пользователей NetSchool"""
    global netschool_users, NETSCHOOL_USERS_FILE_MTIME
    try:
        if Path(NETSCHOOL_USERS_FILE).exists():
            with open(NETSCHOOL_USERS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    netschool_users = data
                else:
                    netschool_users = {"users": {}}
            try:
                NETSCHOOL_USERS_FILE_MTIME = Path(NETSCHOOL_USERS_FILE).stat().st_mtime
            except Exception:
                NETSCHOOL_USERS_FILE_MTIME = 0.0
        else:
            netschool_users = {"users": {}}
            NETSCHOOL_USERS_FILE_MTIME = 0.0
        if "users" not in netschool_users:
            netschool_users["users"] = {}
        logger.info(f"✅ Загружены настройки NetSchool пользователей: {len(netschool_users['users'])}")
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки NetSchool пользователей: {e}")
        netschool_users = {"users": {}}
        NETSCHOOL_USERS_FILE_MTIME = 0.0

def save_netschool_users() -> None:
    """Сохраняет настройки пользователей NetSchool"""
    global NETSCHOOL_USERS_FILE_MTIME
    try:
        with open(NETSCHOOL_USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(netschool_users, f, ensure_ascii=False, indent=2)
        try:
            NETSCHOOL_USERS_FILE_MTIME = Path(NETSCHOOL_USERS_FILE).stat().st_mtime
        except Exception:
            pass
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения NetSchool пользователей: {e}")

def _netschool_user_runtime_signature(user_data: Dict[str, Any]) -> str:
    tracked = {
        "enabled": user_data.get("enabled"),
        "login": user_data.get("login"),
        "password": user_data.get("password"),
        "login_type": user_data.get("login_type"),
        "netschool_url": user_data.get("netschool_url"),
        "netschool_school": user_data.get("netschool_school"),
        "check_interval": user_data.get("check_interval"),
        "notify_mail": user_data.get("notify_mail"),
        "notify_changes": user_data.get("notify_changes"),
        "notify_deletes": user_data.get("notify_deletes"),
        "weekly_summary_enabled": user_data.get("weekly_summary_enabled"),
        "quiet_hours": user_data.get("quiet_hours"),
        "filters": user_data.get("filters"),
        "subject_filters": user_data.get("subject_filters"),
    }
    return json.dumps(tracked, ensure_ascii=False, sort_keys=True)

def _load_grade_feedback_store() -> Dict[str, Any]:
    if not NETSCHOOL_GRADE_FEEDBACK_FILE.exists():
        return {"entries": {}}
    try:
        with open(NETSCHOOL_GRADE_FEEDBACK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
            if isinstance(data, dict):
                entries = data.get("entries")
                if isinstance(entries, dict):
                    return {"entries": entries}
    except Exception as e:
        logger.warning(f"Не удалось загрузить голоса по оценкам: {e}")
    return {"entries": {}}

def _save_grade_feedback_store(store: Dict[str, Any]) -> None:
    try:
        with open(NETSCHOOL_GRADE_FEEDBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Не удалось сохранить голоса по оценкам: {e}")

def _build_grade_feedback_id(assignment: Dict[str, Any]) -> str:
    raw = "|".join([
        str(assignment.get("subjectName", "")),
        str(assignment.get("assignmentType", assignment.get("assignmentName", ""))),
        str(assignment.get("date", "")),
        str(assignment.get("assignmentIndex", "")),
        str(assignment.get("weight", "")),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

def _ensure_grade_feedback_entry(feedback_id: str, assignment: Optional[Dict[str, Any]] = None) -> tuple[Dict[str, Any], Dict[str, Any]]:
    store = _load_grade_feedback_store()
    entries = store.setdefault("entries", {})
    entry = entries.get(feedback_id)
    if not isinstance(entry, dict):
        entry = {}
        entries[feedback_id] = entry

    votes = entry.get("votes")
    if not isinstance(votes, dict):
        entry["votes"] = {}

    if assignment and not isinstance(entry.get("assignment"), dict):
        entry["assignment"] = {
            "subjectName": assignment.get("subjectName", ""),
            "assignmentType": assignment.get("assignmentType", assignment.get("assignmentName", "")),
            "date": assignment.get("date", ""),
            "assignmentIndex": assignment.get("assignmentIndex", ""),
        }

    entry.setdefault("created_at", datetime.now().isoformat())
    entry["updated_at"] = datetime.now().isoformat()
    return store, entry

def _count_grade_feedback_votes(entry: Dict[str, Any]) -> Dict[str, int]:
    counts = {key: 0 for key, _ in GRADE_FEEDBACK_OPTIONS}
    votes = entry.get("votes") or {}
    if isinstance(votes, dict):
        for value in votes.values():
            if value in counts:
                counts[value] += 1
    return counts

def _load_netschool_miniapp_tokens() -> Dict[str, Any]:
    def _normalize(data: Dict[str, Any] | None) -> Dict[str, Any]:
        source = data if isinstance(data, dict) else {}
        tokens = source.get("tokens") if isinstance(source.get("tokens"), dict) else {}
        archived = source.get("archived_tokens") if isinstance(source.get("archived_tokens"), dict) else {}
        return {
            **source,
            "tokens": tokens,
            "archived_tokens": archived,
        }

    if not NETSCHOOL_MINIAPP_TOKENS_FILE.exists():
        return {"tokens": {}, "archived_tokens": {}}
    try:
        with open(NETSCHOOL_MINIAPP_TOKENS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
            if isinstance(data, dict):
                return _normalize(data)
    except Exception as e:
        logger.warning(f"Не удалось загрузить токены миниприложения: {e}")
    return {"tokens": {}, "archived_tokens": {}}

def _save_netschool_miniapp_tokens(data: Dict[str, Any]) -> None:
    try:
        NETSCHOOL_MINIAPP_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **(data if isinstance(data, dict) else {}),
            "tokens": (data or {}).get("tokens") if isinstance((data or {}).get("tokens"), dict) else {},
            "archived_tokens": (data or {}).get("archived_tokens") if isinstance((data or {}).get("archived_tokens"), dict) else {},
        }
        with open(NETSCHOOL_MINIAPP_TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.chmod(NETSCHOOL_MINIAPP_TOKENS_FILE, 0o600)
    except Exception as e:
        logger.warning(f"Не удалось сохранить токены миниприложения: {e}")

def _archive_netschool_miniapp_token(store: Dict[str, Any], token: str, payload: Optional[Dict[str, Any]], reason: str) -> None:
    if not token or not isinstance(payload, dict):
        return
    archived = store.setdefault("archived_tokens", {})
    archived[token] = {
        **payload,
        "archived_at": int(time.time()),
        "archive_reason": str(reason or "invalidated"),
    }

def _cleanup_expired_archived_netschool_miniapp_tokens(store: Dict[str, Any]) -> bool:
    archived = store.setdefault("archived_tokens", {})
    now_ts = int(time.time())
    expired = [
        key for key, payload in archived.items()
        if int((payload or {}).get("archived_at", 0)) + NETSCHOOL_MINIAPP_ARCHIVE_TTL <= now_ts
    ]
    for key in expired:
        archived.pop(key, None)
    return bool(expired)

def _cleanup_expired_miniapp_tokens(store: Dict[str, Any]) -> None:
    tokens = store.setdefault("tokens", {})
    now_ts = int(time.time())
    for token in [key for key, payload in tokens.items() if int((payload or {}).get("expires_at", 0)) <= now_ts]:
        payload = tokens.pop(token, None)
        _archive_netschool_miniapp_token(store, token, payload, "expired")
    _cleanup_expired_archived_netschool_miniapp_tokens(store)

def _issue_netschool_miniapp_token(user_id: int, ttl: Optional[int] = None) -> str:
    store = _load_netschool_miniapp_tokens()
    _cleanup_expired_miniapp_tokens(store)
    token = secrets.token_urlsafe(24)
    token_ttl = NETSCHOOL_MINIAPP_TOKEN_TTL if ttl is None else max(60, int(ttl))
    store.setdefault("tokens", {})[token] = {
        "user_id": user_id,
        "issued_at": int(time.time()),
        "expires_at": int(time.time()) + token_ttl,
    }
    _save_netschool_miniapp_tokens(store)
    return token

def _issue_netschool_pwa_token(user_id: int) -> str:
    return _issue_netschool_miniapp_token(user_id, ttl=86400 * 365)

def _load_netschool_session_codes() -> Dict[str, Any]:
    if not NETSCHOOL_SESSION_CODES_FILE.exists():
        return {"codes": {}}
    try:
        with open(NETSCHOOL_SESSION_CODES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
            if isinstance(data, dict) and isinstance(data.get("codes"), dict):
                return data
    except Exception as e:
        logger.warning(f"Не удалось загрузить recovery-коды PWA: {e}")
    return {"codes": {}}

def _save_netschool_session_codes(store: Dict[str, Any]) -> None:
    try:
        NETSCHOOL_SESSION_CODES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(NETSCHOOL_SESSION_CODES_FILE, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
        os.chmod(NETSCHOOL_SESSION_CODES_FILE, 0o600)
    except Exception as e:
        logger.warning(f"Не удалось сохранить recovery-коды PWA: {e}")

def _cleanup_expired_netschool_session_codes(store: Dict[str, Any]) -> None:
    now_ts = int(time.time())
    codes = store.setdefault("codes", {})
    for code in [key for key, payload in codes.items() if int((payload or {}).get("expires_at", 0)) <= now_ts]:
        codes.pop(code, None)

def _issue_netschool_session_code(user_id: int) -> str:
    store = _load_netschool_session_codes()
    _cleanup_expired_netschool_session_codes(store)
    codes = store.setdefault("codes", {})
    for code in [key for key, payload in codes.items() if int((payload or {}).get("user_id", 0)) == int(user_id)]:
        codes.pop(code, None)
    code = str(secrets.randbelow(900000) + 100000)
    codes[code] = {
        "user_id": int(user_id),
        "expires_at": int(time.time()) + 300,
    }
    _save_netschool_session_codes(store)
    return code

def _load_netschool_miniapp_access_requests() -> Dict[str, Any]:
    if not NETSCHOOL_MINIAPP_ACCESS_REQUESTS_FILE.exists():
        return {"requests": {}}
    try:
        with open(NETSCHOOL_MINIAPP_ACCESS_REQUESTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
            if isinstance(data, dict) and isinstance(data.get("requests"), dict):
                return data
    except Exception as e:
        logger.warning(f"Не удалось загрузить запросы доступа PWA: {e}")
    return {"requests": {}}

def _save_netschool_miniapp_access_requests(store: Dict[str, Any]) -> None:
    try:
        NETSCHOOL_MINIAPP_ACCESS_REQUESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(NETSCHOOL_MINIAPP_ACCESS_REQUESTS_FILE, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
        os.chmod(NETSCHOOL_MINIAPP_ACCESS_REQUESTS_FILE, 0o600)
    except Exception as e:
        logger.warning(f"Не удалось сохранить запросы доступа PWA: {e}")

def _cleanup_expired_netschool_miniapp_access_requests(store: Dict[str, Any]) -> None:
    requests_store = store.setdefault("requests", {})
    now_ts = int(time.time())
    for request_id, entry in list(requests_store.items()):
        if not isinstance(entry, dict):
            requests_store.pop(request_id, None)
            continue
        expires_at = int(entry.get("expires_at") or 0)
        created_at = int(entry.get("created_at") or 0)
        status = str(entry.get("status") or "pending")
        if expires_at and expires_at < now_ts and status == "pending":
            entry["status"] = "expired"
            entry["resolved_at"] = now_ts
        if status in {"approved", "code_sent", "rejected", "expired"} and created_at and created_at + 86400 < now_ts:
            requests_store.pop(request_id, None)

def _format_netschool_pwa_access_status(status: str) -> str:
    return {
        "approved": "вход уже подтверждён",
        "code_sent": "код уже отправлен",
        "rejected": "вход уже отклонён",
        "expired": "запрос уже истёк",
    }.get(status, "запрос уже обработан")

def _load_pwa_gallery() -> list[dict[str, Any]]:
    if not PWA_GALLERY_INDEX_FILE.exists():
        return []
    try:
        with open(PWA_GALLERY_INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("icons", [])
    except Exception as e:
        logger.warning(f"Не удалось загрузить галерею PWA: {e}")
        return []

def _save_pwa_gallery(icons: list[dict[str, Any]]) -> None:
    PWA_GALLERY_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PWA_GALLERY_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump({"icons": icons}, f, ensure_ascii=False, indent=2)

def _pwa_gallery_image_path(gallery_id: str) -> Path:
    return PWA_GALLERY_DIR / f"{gallery_id}.png"

def _delete_pwa_gallery_icon(gallery_id: str) -> tuple[bool, list[dict[str, Any]]]:
    icons = _load_pwa_gallery()
    new_icons = [icon for icon in icons if str(icon.get("id") or "") != gallery_id]
    if len(new_icons) == len(icons):
        return False, icons
    gfile = PWA_GALLERY_DIR / f"{gallery_id}.png"
    if gfile.exists():
        gfile.unlink()
    _save_pwa_gallery(new_icons)
    return True, new_icons

def _revoke_pwa_icon_access(target_user_id: int) -> tuple[int, bool]:
    store = _load_netschool_miniapp_tokens()
    tokens = store.get("tokens", {})
    to_remove = [token_key for token_key, payload in tokens.items() if int(payload.get("user_id", 0)) == target_user_id]
    for key in to_remove:
        del tokens[key]
    if to_remove:
        _save_netschool_miniapp_tokens(store)
    icon_file = NETSCHOOL_MINIAPP_ICONS_DIR / f"{target_user_id}.png"
    icon_deleted = False
    if icon_file.exists():
        icon_file.unlink()
        icon_deleted = True
    return len(to_remove), icon_deleted

def _build_netschool_miniapp_url(token: str) -> Optional[str]:
    if not NETSCHOOL_MINIAPP_BASE_URL:
        return None
    separator = "&" if "?" in NETSCHOOL_MINIAPP_BASE_URL else "?"
    return f"{NETSCHOOL_MINIAPP_BASE_URL}{separator}{urlencode({'token': token})}"

def _clamp_interval(value: int) -> int:
    return max(NETSCHOOL_MIN_INTERVAL, min(NETSCHOOL_MAX_INTERVAL, value))

def get_netschool_user(user_id: int, display_name: Optional[str] = None) -> Dict[str, Any]:
    """Получить или создать запись пользователя NetSchool"""
    users = netschool_users.setdefault("users", {})
    key = str(user_id)
    if key not in users:
        users[key] = {
            "login": "",
            "password": "",
            "netschool_url": "",
            "netschool_school": "",
            "login_type": "password",
            "enabled": False,
            "check_interval": CHECK_INTERVAL,
            "filters": {"exclude": []},
            "subject_filters": {"include": []},
            "quiet_hours": {"start": "", "end": ""},
            "weekly_summary_enabled": False,
            "last_weekly_summary": "",
            "state": None,
            "display_name": display_name or "",
            "student_name": "",
            "selected_student_id": None,
            "available_students": [],
            "bulk_prompt_pending": False,
            "pending_bulk": [],
            "events_prompt_pending": False,
            "pending_events": [],
            "homework_prompt_pending": False,
            "pending_homework": [],
            "notify_changes": True,
            "notify_deletes": True,
            "notify_mail": True,
            "notify_homework": True,
            "push_mode": "both",
            "mail_seen_ids": [],
            "updated_at": datetime.now().isoformat()
        }
        save_netschool_users()
    elif display_name:
        if users[key].get("display_name") != display_name:
            users[key]["display_name"] = display_name
            users[key]["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
    user = users[key]
    if "notify_mail" not in user:
        user["notify_mail"] = True
    if "push_mode" not in user:
        user["push_mode"] = "both"
    if "mail_seen_ids" not in user:
        user["mail_seen_ids"] = []
    if "notify_homework" not in user:
        user["notify_homework"] = True
    if "homework_prompt_pending" not in user:
        user["homework_prompt_pending"] = False
    if "pending_homework" not in user:
        user["pending_homework"] = []
    if "login_type" not in user:
        user["login_type"] = "password"
    if "subject_filters" not in user:
        user["subject_filters"] = {"include": []}
    if "quiet_hours" not in user:
        user["quiet_hours"] = {"start": "", "end": ""}
    if "weekly_summary_enabled" not in user:
        user["weekly_summary_enabled"] = False
    if "last_weekly_summary" not in user:
        user["last_weekly_summary"] = ""
    return users[key]

def _get_user_ns_url(user_data: Dict[str, Any]) -> Optional[str]:
    """URL Сетевого города пользователя.

    Глобального URL по умолчанию нет: пользователь выбирает регион сам.
    """
    return user_data.get("netschool_url") or None

def _normalize_netschool_school_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return text

def _get_user_ns_school(user_data: Dict[str, Any]) -> Any:
    """Школа пользователя.

    Школы по умолчанию нет: каждый выбирает свою при /login.
    """
    return _normalize_netschool_school_value(user_data.get("netschool_school"))

def _netschool_push_url(tab: str = "diary") -> str:
    base = (NETSCHOOL_MINIAPP_BASE_URL or f"{config.PUBLIC_BASE_URL}{config.MINIAPP_PATH}").strip()
    return f"{base}#{tab}"

def _should_send_telegram(user_data: Dict[str, Any]) -> bool:
    return str(user_data.get("push_mode") or "telegram") in {"telegram", "both"}

def _should_send_app_push(user_data: Dict[str, Any]) -> bool:
    return str(user_data.get("push_mode") or "telegram") in {"app", "both"}

async def _send_netschool_web_push(user_id: Optional[int], user_data: Dict[str, Any], title: str, body: str, tab: str) -> bool:
    if not user_id or not _should_send_app_push(user_data):
        return False
    try:
        result = await asyncio.to_thread(
            send_user_push,
            int(user_id),
            title,
            body,
            _netschool_push_url(tab),
            f"netschool-{tab}",
            {"tab": tab},
        )
        return bool(result.get("ok"))
    except Exception as exc:
        logger.warning(f"Web push NetSchool не отправлен: {exc}")
        return False

def set_netschool_user_state(user_id: int, state: Optional[str]) -> None:
    user = get_netschool_user(user_id)
    user["state"] = state
    user["updated_at"] = datetime.now().isoformat()
    save_netschool_users()

def _get_netschool_user_state(user_id: int) -> Optional[str]:
    """Текущее состояние диалога пользователя в NetSchool-флоу."""
    return get_netschool_user(user_id).get("state")

def get_user_exclude_titles(user_data: Dict[str, Any]) -> Set[str]:
    raw = user_data.get("filters", {}).get("exclude") or _default_exclude_titles()
    return { _normalize_title(x) for x in raw if str(x).strip() }

def get_user_display_name(user_id: int, fallback: str = "") -> str:
    user_data = get_netschool_user(user_id)
    return user_data.get("display_name") or fallback or f"ID {user_id}"

def get_user_student_name(user_id: int) -> str:
    user_data = get_netschool_user(user_id)
    return user_data.get("student_name") or ""

def _get_available_students(user_data: Dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in user_data.get("available_students") or []:
        if not isinstance(item, dict):
            continue
        sid = _safe_int(item.get("id"))
        if sid is None:
            continue
        name = str(item.get("name") or "").strip() or f"Ученик {sid}"
        result.append({"id": sid, "name": name})
    if not result:
        fallback_name = str(user_data.get("student_name") or user_data.get("display_name") or "").strip()
        selected_id = _safe_int(user_data.get("selected_student_id")) or 0
        if fallback_name:
            result.append({"id": selected_id, "name": fallback_name})
    return result

def get_user_subject_include_titles(user_data: Dict[str, Any]) -> Set[str]:
    raw = user_data.get("subject_filters", {}).get("include") or []
    return {_normalize_subject(x) for x in raw if str(x).strip()}

def is_subject_allowed_for_user(user_data: Dict[str, Any], subject: str) -> bool:
    include = get_user_subject_include_titles(user_data)
    if not include:
        return True
    return _normalize_subject(subject) in include

def get_user_quiet_hours(user_data: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    quiet = user_data.get("quiet_hours") or {}
    start = _parse_hhmm(str(quiet.get("start") or "")) if quiet.get("start") else None
    end = _parse_hhmm(str(quiet.get("end") or "")) if quiet.get("end") else None
    return start, end

def format_user_quiet_hours(user_data: Dict[str, Any]) -> str:
    start, end = get_user_quiet_hours(user_data)
    if not start or not end:
        return "не настроены"
    return f"{start} - {end}"

def is_user_quiet_hours_now(user_data: Dict[str, Any], now_dt: Optional[datetime] = None) -> bool:
    start, end = get_user_quiet_hours(user_data)
    if not start or not end:
        return False
    now_dt = now_dt or datetime.now(dt_timezone(timedelta(hours=3)))
    now_minutes = now_dt.hour * 60 + now_dt.minute
    start_h, start_m = map(int, start.split(":"))
    end_h, end_m = map(int, end.split(":"))
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m
    if start_minutes == end_minutes:
        return True
    if start_minutes < end_minutes:
        return start_minutes <= now_minutes < end_minutes
    return now_minutes >= start_minutes or now_minutes < end_minutes

