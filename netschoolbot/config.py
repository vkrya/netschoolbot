"""Конфигурация NetSchool-бота.

Все настройки читаются из окружения (.env в корне проекта либо data/.env).
В отличие от старого монолита, здесь НЕТ глобальной школы по умолчанию:
каждый пользователь выбирает регион и школу сам при /login.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# ============= ДИРЕКТОРИИ ДАННЫХ =============
DATA_DIR = Path(os.getenv("NETSCHOOL_DATA_DIR") or (BASE_DIR / "data")).resolve()
load_dotenv(DATA_DIR / ".env", override=False)

NETSCHOOL_USERS_DIR = DATA_DIR / "netschool_users"
NETSCHOOL_SESSIONS_DIR = DATA_DIR / "netschool_sessions"
NETSCHOOL_FEEDBACK_DIR = DATA_DIR / "netschool_feedback"
NETSCHOOL_CACHE_DIR = DATA_DIR / "netschool_cache"
LOGS_DIR = DATA_DIR / "logs"
TMP_DIR = DATA_DIR / "tmp"

NETSCHOOL_MINIAPP_ICONS_DIR = NETSCHOOL_USERS_DIR / "pwa_icons"
NETSCHOOL_MINIAPP_GALLERY_DIR = NETSCHOOL_USERS_DIR / "pwa_gallery"

USERS_FILE = NETSCHOOL_USERS_DIR / "netschool_users.json"
GRADE_FEEDBACK_FILE = NETSCHOOL_USERS_DIR / "grade_feedback_votes.json"
MINIAPP_TOKENS_FILE = NETSCHOOL_USERS_DIR / "miniapp_tokens.json"
MINIAPP_ACCESS_REQUESTS_FILE = NETSCHOOL_USERS_DIR / "miniapp_access_requests.json"
SESSION_CODES_FILE = NETSCHOOL_USERS_DIR / "session_codes.json"
GALLERY_INDEX_FILE = NETSCHOOL_USERS_DIR / "pwa_gallery_index.json"
FEEDBACK_FILE = NETSCHOOL_FEEDBACK_DIR / "feedback.jsonl"
SENT_GRADES_FILE = DATA_DIR / "sent_grades.json"

ENV_FILE_PATH = DATA_DIR / ".env"
INPUT_FIFO = Path(os.getenv("NETSCHOOL_INPUT_FIFO", str(DATA_DIR / "netschoolbot_input.fifo")))


def ensure_data_dirs() -> None:
    for path in (
        DATA_DIR,
        NETSCHOOL_USERS_DIR,
        NETSCHOOL_SESSIONS_DIR,
        NETSCHOOL_FEEDBACK_DIR,
        NETSCHOOL_CACHE_DIR,
        LOGS_DIR,
        TMP_DIR,
        NETSCHOOL_MINIAPP_ICONS_DIR,
        NETSCHOOL_MINIAPP_GALLERY_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def data_path(name: str) -> Path:
    return DATA_DIR / Path(name).name


def get_env_int(key: str, default: int = 0) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    raw = str(raw).split("#", 1)[0].strip().strip("'\"")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


# ============= TELEGRAM =============
BOT_TOKEN = (os.getenv("NETSCHOOL_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN") or "").strip()
LOG_BOT_TOKEN = (os.getenv("LOG_BOT_TOKEN") or "").strip()
ADMIN_ID = get_env_int("TG_ADMIN_ID", 0)
TELEGRAM_LOGGING_ENABLED = get_env_bool("TELEGRAM_LOGGING_ENABLED", True)
TELEGRAM_API_PROXY = (
    os.getenv("TELEGRAM_API_PROXY") or os.getenv("ALL_PROXY") or os.getenv("HTTPS_PROXY") or ""
).strip()

# ============= ОБЩИЙ ЧЕКЕР (в группу) =============
# Остаётся и здесь: общий мониторинг КР/СР/лабораторных для класса.
COMMON_NETSCHOOL_URL = (os.getenv("NETSCHOOL_URL") or "").strip()
COMMON_NETSCHOOL_LOGIN = (os.getenv("NETSCHOOL_LOGIN") or "").strip()
COMMON_NETSCHOOL_PASSWORD = os.getenv("NETSCHOOL_PASSWORD") or ""
COMMON_NETSCHOOL_SCHOOL = (os.getenv("NETSCHOOL_SCHOOL") or "").strip()
COMMON_CHAT_ID = (os.getenv("NETSCHOOL_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
COMMON_TOPIC_ID = get_env_int("TG_TOPIC_GRADES_ID", 0) or None
CHECK_INTERVAL = get_env_int("CHECK_INTERVAL", 300)

# ============= ВЕБ / PWA =============
PUBLIC_BASE_URL = (os.getenv("NETSCHOOL_PUBLIC_URL") or "https://netschool.ikrya.ru").strip().rstrip("/")
MINIAPP_PATH = (os.getenv("NETSCHOOL_MINIAPP_PATH") or "/mini/netschool").strip()
MINIAPP_BASE_URL = (
    os.getenv("NETSCHOOL_MINIAPP_BASE_URL") or f"{PUBLIC_BASE_URL}{MINIAPP_PATH}"
).strip().rstrip("/")

MINIAPP_TOKEN_TTL = get_env_int("NETSCHOOL_MINIAPP_TOKEN_TTL", 900)
MINIAPP_ARCHIVE_TTL = 86400 * 90
MINIAPP_ACCESS_REQUEST_TTL = 600
MINIAPP_ACCESS_REQUEST_RESEND_COOLDOWN = 60
MINIAPP_AUTOSAVE_INTERVAL_SECONDS = max(300, get_env_int("NETSCHOOL_MINIAPP_AUTOSAVE_INTERVAL_SECONDS", 3600))
MINIAPP_CACHE_FRESH_SECONDS = max(60, get_env_int("NETSCHOOL_MINIAPP_CACHE_FRESH_SECONDS", 3600))

# Web push (VAPID)
VAPID_PUBLIC_KEY = (os.getenv("NETSCHOOL_VAPID_PUBLIC_KEY") or "").strip()
VAPID_PRIVATE_KEY = (os.getenv("NETSCHOOL_VAPID_PRIVATE_KEY") or "").strip()
VAPID_SUBJECT = (os.getenv("NETSCHOOL_VAPID_SUBJECT") or "mailto:admin@netschool.ikrya.ru").strip()

# ============= ВЕБ-ПАНЕЛЬ (терминал + файловый менеджер) =============
WEB_ENABLED = get_env_bool("NETSCHOOL_WEB_ENABLED", True)
# Панель управления сервером здесь выключена: она живёт отдельно на
# vdsru.ikrya.ru, а netschool.ikrya.ru отдаёт только мини-приложение.
PANEL_ENABLED = get_env_bool("NETSCHOOL_PANEL_ENABLED", False)
WEB_PORT = get_env_int("WEBTERM_PORT", 8283)
WEB_USER = os.getenv("WEBTERM_USER", "admin")
WEB_PASS = os.getenv("WEBTERM_PASS", "adminpass")
WEB_SECRET = os.getenv("WEBTERM_SECRET", "netschoolbot-super-secret-change-me")
WEB_SECURE_COOKIE = get_env_bool("WEBTERM_SECURE_COOKIE", False)
WEB_COOKIE_SAMESITE = (os.getenv("WEBTERM_COOKIE_SAMESITE") or ("None" if WEB_SECURE_COOKIE else "Lax")).strip()
WEB_SESSION_HOURS = max(1, get_env_int("WEBTERM_SESSION_HOURS", 12))
WEB_JOURNAL_TAIL = get_env_int("WEBTERM_JOURNAL_TAIL", 500)
WEB_FILE_ROOT = Path(os.getenv("WEBTERM_ROOT", "/"))
WEB_AUTH_FILE = Path(os.getenv("WEBTERM_AUTH_FILE", str(DATA_DIR / "webterm_auth.json")))
WEB_STATIC_DIR = BASE_DIR / "static_web"
SERVICE_NAME = os.getenv("NETSCHOOL_SERVICE_NAME", "netschoolbot")

# ============= ИНТЕРВАЛЫ ПРОВЕРКИ =============
MIN_INTERVAL = 180  # 3 минуты
MAX_INTERVAL = 10800  # 3 часа

# ============= ПРОКСИ ДЛЯ РЕГИОНОВ =============
# Некоторые региональные серверы блокируют datacenter-IP.
VOLGOGRAD_PROXY = os.getenv("VOLGOGRAD_PROXY") or "socks5://127.0.0.1:1080"
PROXY_REQUIRED_HOSTS: dict[str, str | None] = {
    "sgo.volganet.ru": VOLGOGRAD_PROXY,
}

ERROR_NOTIFICATIONS_ENABLED = get_env_bool("NETSCHOOL_ERROR_NOTIFICATIONS", True)
ERROR_NOTIFICATION_COOLDOWN = 300

DEBUG_MODE = get_env_bool("DEBUG_MODE", False)
