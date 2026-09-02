"""Общее состояние бота: экземпляры Bot, фоновые задачи пользователей.

Модуль намеренно не импортирует ничего из handlers/tasks, чтобы его можно
было использовать откуда угодно без циклических импортов.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:  # pragma: no cover
    import asyncio

    from aiogram import Bot

# Основной бот NetSchool и бот логирования
bot: Optional["Bot"] = None
log_bot: Optional["Bot"] = None
admin_id: Optional[int] = None

# user_id -> asyncio.Task индивидуального чекера
netschool_user_tasks: Dict[int, "asyncio.Task"] = {}
# user_id -> GradeNotifier
netschool_user_notifiers: Dict[int, Any] = {}
# user_id -> asyncio.Task повторных попыток входа
netschool_login_retry_tasks: Dict[int, "asyncio.Task"] = {}

# Временные кеши диалогов (user_id -> данные)
GRADES_SUBJECTS_CACHE: Dict[int, Dict[str, Any]] = {}
GRADES_SUBJECTS_PAGE_SIZE = 10
HOMEWORK_ATTACHMENTS_CACHE: Dict[int, list] = {}
MAIL_ATTACHMENTS_CACHE: Dict[int, Dict[int, list]] = {}
# Временный кеш школ при поиске (user_id -> [school_name, ...])
_SCHOOL_SEARCH_CACHE: Dict[int, list] = {}


def set_bots(main_bot: "Bot", logging_bot: Optional["Bot"] = None, admin: Optional[int] = None) -> None:
    global bot, log_bot, admin_id
    bot = main_bot
    log_bot = logging_bot
    admin_id = admin
