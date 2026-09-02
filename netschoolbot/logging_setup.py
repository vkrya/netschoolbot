"""Логирование: файлы сессий, ротация и отправка логов администратору в Telegram."""

import asyncio
import html
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .config import DEBUG_MODE, LOGS_DIR, TELEGRAM_LOGGING_ENABLED
from .utils import _msk_time, now_msk, write_json_atomic

LAST_LOGS_FILENAME = "lastlogs.txt"
LAST_START_META_FILENAME = ".last_start.txt"
LOG_FILTERS_FILE = LOGS_DIR / "log_filters.json"

telegram_logging_enabled = TELEGRAM_LOGGING_ENABLED

_DEFAULT_LOG_FILTERS = {
    "netschool": True,
    "aiogram": True,
    "flask": True,
    "other": True,
}


def get_log_filters() -> Dict[str, bool]:
    """Фильтры пересылки логов в Telegram (хранятся в data/logs/log_filters.json)."""
    try:
        if LOG_FILTERS_FILE.exists():
            data = json.loads(LOG_FILTERS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**_DEFAULT_LOG_FILTERS, **data}
    except Exception:
        pass
    return dict(_DEFAULT_LOG_FILTERS)


def save_log_filters(filters: Dict[str, bool]) -> None:
    try:
        write_json_atomic(LOG_FILTERS_FILE, filters)
    except Exception:
        pass


def _format_log_start(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y-%H-%M-%S")


def _get_logs_base_dir() -> Path:
    return LOGS_DIR


def _session_logs_dir_name(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _get_logs_dir() -> Path:
    return _get_logs_base_dir() / _session_logs_dir_name(SESSION_START_AT)


def _try_parse_start_date(value: str) -> Optional[datetime]:
    try:
        date_part = value.split("-")[0]
        return datetime.strptime(date_part, "%d.%m.%Y")
    except Exception:
        return None


SESSION_START_AT = now_msk()
SESSION_START_STR = _format_log_start(SESSION_START_AT)
LOG_FILES_PREPARED = False
CURRENT_LOG_FILE_PATH: Optional[Path] = None


def prepare_log_files() -> Path:
    """Подготовка папки логов и ротация lastlogs.txt в файл с датой старта."""
    base_dir = _get_logs_base_dir()
    base_dir.mkdir(parents=True, exist_ok=True)

    session_dir = _get_logs_dir()
    session_dir.mkdir(parents=True, exist_ok=True)

    last_start_meta = base_dir / LAST_START_META_FILENAME

    prev_start: Optional[str] = None
    if last_start_meta.exists():
        try:
            prev_start = last_start_meta.read_text(encoding="utf-8").strip() or None
        except Exception:
            prev_start = None

    def _rotate_last_log(path: Path) -> None:
        nonlocal prev_start
        if not path.exists():
            return

        if not prev_start:
            try:
                prev_start = _format_log_start(datetime.fromtimestamp(path.stat().st_mtime))
            except Exception:
                prev_start = SESSION_START_STR

        target_dir = base_dir
        parsed_date = _try_parse_start_date(prev_start)
        if parsed_date:
            target_dir = base_dir / _session_logs_dir_name(parsed_date)
            target_dir.mkdir(parents=True, exist_ok=True)

        target = target_dir / f"logs-{prev_start}.txt"
        if target.exists():
            counter = 1
            while target.exists():
                target = target_dir / f"logs-{prev_start}-{counter}.txt"
                counter += 1

        try:
            path.rename(target)
        except Exception:
            pass

    # Ротация старого lastlogs.txt (старый формат в корне)
    _rotate_last_log(base_dir / LAST_LOGS_FILENAME)
    # Ротация lastlogs.txt в папке текущей даты (если перезапуск в тот же день)
    _rotate_last_log(session_dir / LAST_LOGS_FILENAME)

    try:
        last_start_meta.write_text(SESSION_START_STR, encoding="utf-8")
    except Exception:
        pass

    return session_dir / LAST_LOGS_FILENAME

# ============= TELEGRAM LOG HANDLER =============
class TelegramLogHandler(logging.Handler):
    """Кастомный обработчик логов для отправки в Telegram с защитой от Flood Control"""
    
    def __init__(self, bot_token: str, admin_id: int, level=logging.INFO):
        super().__init__(level)
        self.bot_token = bot_token
        self.admin_id = admin_id
        self.bot = None
        self.log_queue = []
        self.last_send_time = 0
        self.send_interval = 180  # Отправлять батч логов каждые 3 минуты (защита от Flood Control)
        self.max_queue_size = 50  # Максимум логов в батче (увеличено для меньшего количества отправок)
        self.loop = None
        self.flood_control_until = 0  # Время до которого действует Flood Control
        self.max_queue_limit = 200  # Максимальный размер очереди (защита от переполнения)
        
    async def _init_bot(self):
        """Инициализация бота (вызывается асинхронно)"""
        if not self.bot:
            from aiogram import Bot
            self.bot = _create_bot(self.bot_token)
    
    async def _send_log_batch(self):
        """Отправка батча логов в Telegram с обработкой Flood Control"""
        if not self.log_queue:
            return
        
        # Проверяем, не действует ли Flood Control
        current_time = time.time()
        if current_time < self.flood_control_until:
            # Flood Control еще активен, пропускаем отправку
            return
        
        try:
            if not self.bot:
                await self._init_bot()
            
            # Объединяем логи в одно сообщение
            message = "\n".join(self.log_queue[:self.max_queue_size])

            # Разбиваем длинные сообщения на части
            chunks: list[str] = []
            max_len = 3900
            while message:
                chunks.append(message[:max_len])
                message = message[max_len:]

            for idx, part in enumerate(chunks, start=1):
                await self.bot.send_message(
                    self.admin_id,
                    f"<pre>{html.escape(part)}</pre>",
                    parse_mode='HTML'
                )
            
            # Очищаем отправленные логи
            self.log_queue = self.log_queue[self.max_queue_size:]
            self.last_send_time = time.time()
            
        except Exception as e:
            error_str = str(e)
            
            # Проверяем, это ошибка Flood Control
            if 'flood control' in error_str.lower() or 'retry after' in error_str.lower():
                # Извлекаем время ожидания
                import re
                match = re.search(r'retry (?:after|in) (\d+)', error_str.lower())
                if match:
                    retry_after = int(match.group(1))
                    self.flood_control_until = time.time() + retry_after
                    print(f"⚠️ Telegram Flood Control: ожидание {retry_after} секунд ({retry_after // 60} минут)")
                    # Очищаем очередь, чтобы не накапливать слишком много логов
                    if len(self.log_queue) > self.max_queue_limit:
                        removed = len(self.log_queue) - self.max_queue_limit
                        self.log_queue = self.log_queue[-self.max_queue_limit:]
                        print(f"⚠️ Очередь логов переполнена, удалено {removed} старых записей")
                else:
                    # Если не удалось извлечь время, ждем 1 час
                    self.flood_control_until = time.time() + 3600
                    print(f"⚠️ Telegram Flood Control: ожидание 1 час (не удалось определить точное время)")
            else:
                # Другая ошибка, просто выводим
                print(f"Failed to send log to Telegram: {e}")
    
    def emit(self, record):
        """Обработка лог-записи"""
        try:
            # Проверяем, включено ли Telegram логирование
            global telegram_logging_enabled
            if not telegram_logging_enabled:
                return

            filters = get_log_filters()
            name = record.name.lower()
            if name.startswith("netschoolpy"):
                if not filters.get("netschool", True):
                    return
            elif name.startswith("pymax"):
                if not filters.get("pymax", True):
                    return
            elif name.startswith("aiogram"):
                if not filters.get("aiogram", True):
                    return
            elif name.startswith("telethon"):
                if not filters.get("telethon", True):
                    return
            else:
                if not filters.get("other", True):
                    return
            
            # Форматируем сообщение
            log_entry = self.format(record)
            
            # Добавляем в очередь (с ограничением размера)
            self.log_queue.append(log_entry)
            
            # Ограничиваем размер очереди
            if len(self.log_queue) > self.max_queue_limit:
                # Удаляем старые логи
                self.log_queue = self.log_queue[-self.max_queue_limit:]
            
            # Проверяем, нужно ли отправить батч
            current_time = time.time()
            
            # Не отправляем, если действует Flood Control
            if current_time < self.flood_control_until:
                return
            
            should_send = (
                len(self.log_queue) >= self.max_queue_size or
                current_time - self.last_send_time >= self.send_interval
            )
            
            if should_send and self.loop:
                # Создаем задачу для отправки
                asyncio.run_coroutine_threadsafe(
                    self._send_log_batch(),
                    self.loop
                )
        except Exception:
            self.handleError(record)
    
    def set_event_loop(self, loop):
        """Установка event loop для асинхронной отправки"""
        self.loop = loop

def setup_logging(debug: bool = False):
    """Настройка уровня логирования"""
    level = logging.DEBUG if debug else logging.INFO

    global LOG_FILES_PREPARED, CURRENT_LOG_FILE_PATH
    if not LOG_FILES_PREPARED or CURRENT_LOG_FILE_PATH is None:
        CURRENT_LOG_FILE_PATH = prepare_log_files()
        LOG_FILES_PREPARED = True

    log_file_path = CURRENT_LOG_FILE_PATH
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    stream_handler = logging.StreamHandler()
    for handler in (file_handler, stream_handler):
        try:
            handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            handler.formatter.converter = _msk_time
        except Exception:
            pass
    
    # Настройка корневого логгера
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[stream_handler, file_handler],
        force=True  # Перезаписать существующую конфигурацию
    )
    
    # Настройка специфичных логгеров
    if debug:
        logging.getLogger("netschoolpy").setLevel(logging.DEBUG)
        logging.getLogger("marshmallow").setLevel(logging.DEBUG)
        logging.getLogger("aiogram").setLevel(logging.DEBUG)
    else:
        logging.getLogger("netschoolpy").setLevel(logging.WARNING)
        logging.getLogger("marshmallow").setLevel(logging.WARNING)
        logging.getLogger("aiogram").setLevel(logging.INFO)
    
    return level


def _create_bot(token: str):
    from .bot.factory import create_tg_bot

    return create_tg_bot(token)


def _log_unhandled_exception(exc_type, exc, tb):
    logging.getLogger("netschoolbot").critical("❌ Необработанное исключение", exc_info=(exc_type, exc, tb))


def init_logging(debug: bool = DEBUG_MODE) -> logging.Logger:
    setup_logging(debug)
    sys.excepthook = _log_unhandled_exception
    log = logging.getLogger("netschoolbot")
    log.info(f"🟢 Старт логирования сессии: {SESSION_START_STR}")
    return log
