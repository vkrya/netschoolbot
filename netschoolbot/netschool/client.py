"""Клиент «Сетевого города»: создание, восстановление и закрытие сессий,
классификация ошибок, работа со списком учеников."""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, Optional

from netschoolpy import NetSchool
import netschoolpy.exceptions as netschoolpy_exceptions

from ..config import (
    NETSCHOOL_SESSIONS_DIR,
    PROXY_REQUIRED_HOSTS as _PROXY_REQUIRED_HOSTS,
    get_env_int,
)
from ..storage import get_netschool_user, save_netschool_users
from ..utils import _safe_int

logger = logging.getLogger("netschoolbot")

NETSCHOOL_SESSION_TTL = get_env_int("NETSCHOOL_SESSION_TTL", 1800)
# user_id -> {"client": NetSchool, "last_used": datetime}
NETSCHOOL_SESSION_CACHE: Dict[int, Dict[str, Any]] = {}
# QR-сессии (долгоживущие)
_ns_clients: Dict[int, Any] = {}
# Фьючерсы для ожидания OTP-кода от пользователя (ESIA MFA)
esia_otp_futures: Dict[int, asyncio.Future] = {}


def _netschool_session_path(user_id: int) -> Path:
    return NETSCHOOL_SESSIONS_DIR / f"session_{user_id}.json"

async def _try_restore_netschool_session(user_id: int, ns: NetSchool) -> bool:
    path = _netschool_session_path(user_id)
    if not path.exists():
        return False
    try:
        session_data = path.read_text(encoding="utf-8")
        await ns.import_session(session_data)
        return True
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return False

def _save_netschool_session(user_id: int, ns: NetSchool) -> None:
    try:
        data = ns.export_session()
        _netschool_session_path(user_id).write_text(data, encoding="utf-8")
    except Exception:
        pass

def _is_gosuslugi_login_type(user_id: int) -> bool:
    try:
        user_data = get_netschool_user(user_id)
    except Exception:
        return False
    return str(user_data.get("login_type") or "").lower() in {"esia", "esia_qr"}

async def _close_netschool_client(ns: Optional[NetSchool], do_logout: bool = True) -> None:
    if not ns:
        return
    try:
        if do_logout:
            try:
                await ns.logout()
            except Exception:
                pass
        if hasattr(ns, "_http"):
            http = ns._http
            if hasattr(http, "aclose"):
                await http.aclose()
            elif hasattr(http, "close"):
                if __import__('asyncio').iscoroutinefunction(getattr(http, 'close')):
                    await http.close()
                else:
                    http.close()
        else:
            await ns.close()
    except Exception:
        pass

def _get_proxy_for_url(url: str) -> str | None:
    """Возвращает прокси для данного URL (если требуется)."""
    for host, px in _PROXY_REQUIRED_HOSTS.items():
        if host in url:
            return px
    return None

def _make_netschool(url: str) -> "NetSchool":
    """Создаёт NetSchool-клиент, используя прокси если нужно для данного URL."""
    proxy = _get_proxy_for_url(url)
    if proxy:
        return NetSchool(url, proxy=proxy)
    return NetSchool(url)

def is_server_unavailable_error(e: Exception) -> bool:
    if isinstance(e, netschoolpy_exceptions.ServerUnavailable):
        return True
    name = type(e).__name__
    text = str(e).lower()
    return (
        "noresponsefromserver" in name.lower()
        or "timeout" in name.lower()
        or "timeout" in text
        or "temporarily unavailable" in text
        or "service unavailable" in text
        or "all connection attempts failed" in text
        or "connecterror" in name.lower()
        or "connectionerror" in name.lower()
        or "connectorerror" in name.lower()
        or "server disconnected" in text
    )

def is_netschool_auth_error(e: Exception) -> bool:
    auth_error_cls = getattr(netschoolpy_exceptions, "AuthError", None)
    if auth_error_cls is not None and isinstance(e, auth_error_cls):
        return True
    name = type(e).__name__.lower()
    text = str(e).lower()
    return (
        "401" in text
        or "unauthorized" in text
        or "not authorized" in text
        or "authorization required" in text
        or "session expired" in text
        or "не авториз" in text
        or "forbidden" in text
        or "autherror" in name
        or "unauthorized" in name
    )

async def _netschool_session_is_alive(ns: NetSchool) -> Optional[bool]:
    try:
        response = await ns._authed_get("student/diary/init")
        status_code = getattr(response, "status_code", None)
        if status_code in (401, 403):
            return False
        return True
    except Exception as e:
        if is_netschool_auth_error(e):
            return False
        if is_server_unavailable_error(e):
            return None
        return None

def is_esia_connection_error(e: Exception) -> bool:
    """Ошибка подключения именно к Госуслугам (ESIA), а не к СГО."""
    if isinstance(e, netschoolpy_exceptions.ESIAError):
        return True
    text = str(e).lower()
    return (
        "esia" in text
        or "gosuslugi" in text
    )

def _classify_login_error(e: Exception) -> str:
    """Вернуть пользователю понятное сообщение об ошибке входа."""
    if isinstance(e, netschoolpy_exceptions.ESIAError):
        return "esia"
    if is_server_unavailable_error(e):
        text = str(e).lower()
        if "esia" in text or "gosuslugi" in text:
            return "esia"
        return "server"
    return "other"

async def _fetch_student_name(ns: NetSchool) -> Optional[str]:
    try:
        student_id = _safe_int(getattr(ns, "_student_id", None))
        response = await ns._authed_get("student/diary/init")
        diary_info = response.json()
        students, current_id = _extract_students_from_diary_info(diary_info)
        target_id = student_id if student_id is not None else current_id
        for student in students:
            if target_id is not None and student["id"] == target_id:
                return student["name"]
        if students:
            return students[0]["name"]
    except Exception:
        return None

def _extract_students_from_diary_info(diary_info: Dict[str, Any]) -> tuple[list[dict[str, Any]], Optional[int]]:
    raw_students = diary_info.get("students") or {}
    current_raw = diary_info.get("currentStudentId")
    current_id = _safe_int(current_raw)
    normalized: list[dict[str, Any]] = []

    items: list[tuple[Any, Any]]
    if isinstance(raw_students, dict):
        items = list(raw_students.items())
    elif isinstance(raw_students, list):
        items = list(enumerate(raw_students))
    else:
        items = []

    for key, student in items:
        if not isinstance(student, dict):
            continue
        sid = _safe_int(student.get("studentId"))
        if sid is None:
            sid = _safe_int(key)
        if sid is None:
            continue
        name = (
            str(student.get("fio") or "").strip()
            or str(student.get("fullName") or "").strip()
            or str(student.get("name") or "").strip()
            or f"Ученик {sid}"
        )
        normalized.append({
            "id": sid,
            "name": name,
            "is_current": current_id is not None and sid == current_id,
        })

    if current_id is None and normalized:
        current_id = normalized[0]["id"]
    return normalized, current_id

def _apply_selected_student_to_client(ns: NetSchool, user_data: Dict[str, Any]) -> Optional[int]:
    selected_id = _safe_int(user_data.get("selected_student_id"))
    if selected_id is None:
        return None
    try:
        setattr(ns, "_student_id", selected_id)
    except Exception:
        return None
    return selected_id

async def _sync_user_students_from_ns(
    ns: NetSchool,
    user_data: Dict[str, Any],
    *,
    persist: bool = True,
    preferred_student_id: Optional[int] = None,
) -> tuple[list[dict[str, Any]], Optional[int], Optional[str]]:
    response = await ns._authed_get("student/diary/init")
    diary_info = response.json()
    students, current_id = _extract_students_from_diary_info(diary_info)
    preferred = preferred_student_id if preferred_student_id is not None else _safe_int(user_data.get("selected_student_id"))
    available_ids = {entry["id"] for entry in students}
    selected_id = preferred if preferred in available_ids else current_id

    selected_name: Optional[str] = None
    for entry in students:
        if selected_id is not None and entry["id"] == selected_id:
            selected_name = entry["name"]
            break
    if selected_id is not None:
        try:
            setattr(ns, "_student_id", int(selected_id))
        except Exception:
            pass

    changed = False
    normalized_students = [{"id": item["id"], "name": item["name"]} for item in students]
    if user_data.get("available_students") != normalized_students:
        user_data["available_students"] = normalized_students
        changed = True
    if selected_id is not None and _safe_int(user_data.get("selected_student_id")) != int(selected_id):
        user_data["selected_student_id"] = int(selected_id)
        changed = True
    if selected_name and user_data.get("student_name") != selected_name:
        user_data["student_name"] = selected_name
        changed = True

    if changed:
        user_data["updated_at"] = datetime.now().isoformat()
        if persist:
            save_netschool_users()
    return normalized_students, selected_id, selected_name

async def _close_netschool_session(user_id: int) -> None:
    await _close_netschool_session_for_user(user_id)

async def _close_netschool_session_for_user(
    user_id: int,
    *,
    clear_saved: bool = False,
    keep_gosuslugi: bool = False,
) -> None:
    if keep_gosuslugi and _is_gosuslugi_login_type(user_id):
        return

    clients: list[NetSchool] = []
    entry = NETSCHOOL_SESSION_CACHE.pop(user_id, None)
    if entry:
        ns = entry.get("client")
        if ns:
            clients.append(ns)
    extra_client = _ns_clients.pop(user_id, None)
    if extra_client:
        clients.append(extra_client)

    seen: set[int] = set()
    for ns in clients:
        ns_id = id(ns)
        if ns_id in seen:
            continue
        seen.add(ns_id)
        await _close_netschool_client(ns, do_logout=False)

    if clear_saved:
        try:
            _netschool_session_path(user_id).unlink(missing_ok=True)
        except Exception:
            pass

async def _close_all_netschool_sessions(*, keep_gosuslugi: bool = False) -> None:
    from ..bot.runtime import netschool_user_notifiers

    user_ids = {
        *NETSCHOOL_SESSION_CACHE.keys(),
        *_ns_clients.keys(),
        *netschool_user_notifiers.keys(),
    }
    for user_id in list(user_ids):
        try:
            await _close_netschool_session_for_user(user_id, keep_gosuslugi=keep_gosuslugi)
        except Exception as exc:
            logger.debug(f"Не удалось закрыть сессию NetSchool для {user_id}: {exc}")

async def _fetch_diary_days(ns: NetSchool, weeks_back: int = 5, weeks_forward: int = 5) -> list[Any]:
    """Получить список дней дневника за диапазон недель."""
    all_days: list[Any] = []
    today = datetime.now(dt_timezone(timedelta(hours=3))).date()
    start_date = today - timedelta(weeks=weeks_back)
    end_date = today + timedelta(weeks=weeks_forward)
    current = start_date - timedelta(days=start_date.weekday())
    while current <= end_date:
        try:
            diary = await ns.diary(start=current)
            if getattr(diary, "schedule", None):
                for day in diary.schedule:
                    if not any(d.day == day.day for d in all_days):
                        all_days.append(day)
        except Exception as e:
            logger.warning(f"Ошибка при запросе недели {current}: {e}")
            await _notify_netschool_error(f"Ошибка при запросе недели {current}: {e}")
        current = current + timedelta(days=7)
    return all_days

async def _fetch_days_for_period(ns: NetSchool, start_date: datetime.date, end_date: datetime.date) -> list[Any]:
    today_d = datetime.now(dt_timezone(timedelta(hours=3))).date()
    weeks_back = max(0, (today_d - start_date).days // 7 + 1) if start_date < today_d else 0
    weeks_forward = max(0, (end_date - today_d).days // 7 + 1) if end_date > today_d else 0
    return await _fetch_diary_days(ns, weeks_back=weeks_back, weeks_forward=weeks_forward)

