"""Мелкие утилиты: нормализация текста, даты, форматирование."""

import datetime as _dt
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Optional

def _normalize_title(value: str) -> str:
    return " ".join(str(value or "").lower().split())

def _normalize_subject(value: str) -> str:
    return " ".join(str(value or "").lower().split())

def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None

def _parse_hhmm(value: str) -> Optional[str]:
    try:
        return datetime.strptime(value.strip(), "%H:%M").strftime("%H:%M")
    except Exception:
        return None

def _split_message(text: str, max_len: int = 3500) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        add_len = len(line) + 1
        if current and current_len + add_len > max_len:
            parts.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += add_len
    if current:
        parts.append("\n".join(current))
    return parts

def _format_timedelta(delta: timedelta) -> str:
    total = max(0, int(delta.total_seconds()))
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    if hours:
        return f"{hours}ч {minutes}м"
    if minutes:
        return f"{minutes}м {seconds}с"
    return f"{seconds}с"

def _parse_date_input(raw: str, base: Optional[datetime.date] = None) -> Optional[datetime.date]:
    if not raw:
        return None
    value = raw.strip()
    base = base or datetime.now(dt_timezone(timedelta(hours=3))).date()
    try:
        if value.count(".") == 1:
            day_str, month_str = value.split(".")
            day = int(day_str)
            month = int(month_str)
            return datetime(base.year, month, day).date()
        if value.count(".") == 2:
            day_str, month_str, year_str = value.split(".")
            day = int(day_str)
            month = int(month_str)
            year = int(year_str)
            if year < 100:
                year += 2000
            return datetime(year, month, day).date()
    except Exception:
        return None
    return None

def _format_date_label(day: datetime.date) -> str:
    weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    return f"{weekday_names[day.weekday()]} {day.strftime('%d.%m')}"

def _file_count_label(n: int) -> str:
    """'1 файл' / '2 файла' / '5 файлов'"""
    if n == 1:
        return "Файл"
    if 2 <= n <= 4:
        return f"{n} файла"
    return f"{n} файлов"

def _clean_assignment_content(content: str) -> str:
    text = (content or "").strip()
    text = text.replace("---Не указана---", "").strip()
    if text.lower() == "не указана":
        return ""
    return text

def _format_assignment_title(kind: str, content: str) -> str:
    kind = (kind or "Задание").strip()
    content = _clean_assignment_content(content)
    if not content:
        return kind
    return f"{kind} {content}".strip()

def _parse_mark_value(mark: Any) -> Optional[float]:
    if isinstance(mark, (int, float)):
        return float(mark)
    if isinstance(mark, str):
        mark_str = mark.strip().replace(",", ".")
        if mark_str.replace(".", "", 1).isdigit():
            return float(mark_str)
    return None

def _match_subject(subjects: list[str], query: str) -> tuple[Optional[str], list[str]]:
    normalized = _normalize_subject(query)
    if not normalized:
        return None, []
    exact = [s for s in subjects if _normalize_subject(s) == normalized]
    if exact:
        return exact[0], exact
    partial = [s for s in subjects if normalized in _normalize_subject(s)]
    if len(partial) == 1:
        return partial[0], partial
    return None, partial

def _msk_tz():
    return dt_timezone(timedelta(hours=3))

def now_msk() -> datetime:
    return datetime.now(_msk_tz())

def _msk_time(*args):
    return now_msk().timetuple()

def _next_three_days(from_date: datetime.date) -> list[datetime.date]:
    """Возвращает до 3 ближайших будних дней начиная с from_date.
    Если сегодня Пт — [Пт, Пн, Вт]. Если Сб/Вс — начинаем с Пн."""
    result: list[datetime.date] = []
    day = from_date
    # Если суббота или воскресенье — перескакиваем на понедельник
    if day.weekday() == 5:  # Сб
        day += timedelta(days=2)
    elif day.weekday() == 6:  # Вс
        day += timedelta(days=1)
    while len(result) < 3:
        if day.weekday() < 5:  # Пн-Пт
            result.append(day)
        day += timedelta(days=1)
    return result

def _current_quarter_start(today=None):
    """Возвращает приблизительную дату начала текущей учебной четверти (Россия)."""
    if today is None:
        today = datetime.now(dt_timezone(timedelta(hours=3))).date()
    month = today.month
    year = today.year
    # datetime здесь — класс datetime.datetime, поэтому создаём date через .date()
    if 9 <= month <= 10:          # 1-я четверть: с 1 сентября
        return datetime(year, 9, 1).date()
    elif 11 <= month <= 12:       # 2-я четверть: с ~1 ноября
        return datetime(year, 11, 1).date()
    elif month == 1:
        if today.day >= 9:        # 3-я четверть уже началась (~9 января)
            return datetime(year, 1, 9).date()
        else:                     # зимние каникулы — ещё 2-я четверть
            return datetime(year - 1, 11, 1).date()
    elif month in (2, 3):         # 3-я четверть продолжается
        return datetime(year, 1, 9).date()
    elif 4 <= month <= 5:         # 4-я четверть: с ~1 апреля
        return datetime(year, 4, 1).date()
    else:                         # лето — показываем 4-ю четверть
        return datetime(year, 4, 1).date()

def _quarter_start_for_user(user_data: dict, today=None):
    q = user_data.get("selected_quarter", None)
    if not q:
        return _current_quarter_start(today)
    if today is None:
        today = datetime.now(dt_timezone(timedelta(hours=3))).date()
    year = today.year
    if today.month < 8:
        year -= 1
    if q == 1:
        return datetime(year, 9, 1).date()
    elif q == 2:
        return datetime(year, 11, 1).date()
    elif q == 3:
        return datetime(year + 1, 1, 9).date()
    elif q == 4:
        return datetime(year + 1, 4, 1).date()
    return _current_quarter_start(today)

def _extract_mark_value(mark: Any) -> Optional[Any]:
    if mark is None:
        return None
    # Support for passing assignment object directly
    if hasattr(mark, "textMark") and getattr(mark, "textMark", None):
        return getattr(mark, "textMark")
    if hasattr(mark, "mark"):
        # if the object has both textMark and mark, we already handled textMark
        mark_val = getattr(mark, "mark", None)
        if hasattr(mark_val, "textMark") and getattr(mark_val, "textMark", None):
            return getattr(mark_val, "textMark")
        # In case the assignment itself is passed, and we need its mark:
        if isinstance(mark_val, dict) and mark_val.get("textMark"):
            return mark_val["textMark"]
        if mark_val is not None:
            return mark_val

    if isinstance(mark, dict):
        if mark.get("textMark"):
            return mark.get("textMark")
        return mark.get("mark") or mark.get("value") or mark.get("name")

    if isinstance(mark, (int, float)):
        return mark
    if isinstance(mark, str):
        cleaned = mark.strip()
        return cleaned or None
    return None

def _mark_to_int(mark: Any) -> Optional[int]:
    value = _extract_mark_value(mark)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ivalue = int(value)
        return ivalue if 1 <= ivalue <= 10 else None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    ivalue = int(match.group(0))
    return ivalue if 1 <= ivalue <= 10 else None

def parse_interval_input(raw: str) -> Optional[int]:
    if not raw:
        return None
    value = raw.strip().lower()
    # Поддержка русских букв: 'м' → 'm', 'с' → 's', 'ч' → 'h'
    value = value.replace('м', 'm').replace('с', 's').replace('ч', 'h')
    try:
        if value.endswith("h"):
            hours = int(value[:-1])
            return hours * 3600
        if value.endswith("m"):
            minutes = int(value[:-1])
            return minutes * 60
        if value.endswith("s"):
            return int(value[:-1])
        return int(value)
    except Exception:
        return None


def write_json_atomic(path, data: Any, *, mode: Optional[int] = None, indent: int = 2) -> None:
    """Атомарно записывает JSON: временный файл рядом + os.replace.

    Файлы состояния пишут и поток бота, и поток веб-панели. Обычная запись
    (open(..., "w")) сначала обрезает файл, поэтому читатель в этот момент
    видит пустоту, откатывается на значение по умолчанию и затем сохраняет
    его поверх — так терялись данные пользователей.
    """
    import json
    import os
    import tempfile
    from pathlib import Path as _Path

    target = _Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        if mode is None:
            # mkstemp создаёт файл с 0600 — сохраняем права уже существующего
            # файла, чтобы атомарная запись не меняла режим доступа молча.
            try:
                mode = target.stat().st_mode & 0o777
            except OSError:
                mode = 0o644
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
