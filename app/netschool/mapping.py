"""Преобразование ответов netschoolpy в доменные записи.

Вынесено отдельно и без сети: разбор чужих объектов — самая хрупкая часть
(библиотека отдаёт то объект, то словарь, то None), и её нужно уметь
проверять тестами на зафиксированных примерах ответов.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..domain.records import Attachment, DiaryDay, HomeworkRecord, MarkRecord, clean_content, extract_mark

logger = logging.getLogger("netschoolbot.netschool")

# Домашние задания за пределами этого окна не показываем: прошлые уже не
# нужны, а слишком далёкие будущие школа обычно ещё правит.
HOMEWORK_PAST_DAYS = 1
HOMEWORK_FUTURE_DAYS = 30


def _attr(source: Any, name: str, default: Any = None) -> Any:
    """Достать поле хоть из объекта, хоть из словаря."""
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _time_text(value: Any) -> str:
    return value.strftime("%H:%M") if hasattr(value, "strftime") else ""


def _as_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def marks_from_day(day: Any) -> list[MarkRecord]:
    """Все выставленные оценки одного дня дневника."""
    day_date = _as_date(_attr(day, "day"))
    if day_date is None:
        return []

    records: list[MarkRecord] = []
    for lesson in _attr(day, "lessons", []) or []:
        subject = str(_attr(lesson, "subject", "") or "—")
        lesson_number = _attr(lesson, "number")
        lesson_start = _time_text(_attr(lesson, "start"))
        lesson_end = _time_text(_attr(lesson, "end"))

        for index, assignment in enumerate(_attr(lesson, "assignments", []) or []):
            mark = extract_mark(assignment)
            if not mark:
                continue
            records.append(
                MarkRecord(
                    subject=subject,
                    date=day_date,
                    assignment_type=str(
                        _attr(assignment, "kind") or _attr(assignment, "type") or "Задание"
                    ).strip(),
                    content=str(_attr(assignment, "content", "") or ""),
                    mark=mark,
                    weight=int(_attr(assignment, "weight") or 1),
                    comment=str(_attr(assignment, "comment", "") or ""),
                    lesson_number=lesson_number,
                    lesson_start=lesson_start,
                    lesson_end=lesson_end,
                    assignment_index=index,
                )
            )
    return records


def homework_from_day(day: Any, *, today: dt.date | None = None) -> list[HomeworkRecord]:
    """Домашние задания одного дня дневника, отфильтрованные по актуальности."""
    day_date = _as_date(_attr(day, "day"))
    if day_date is None:
        return []
    today = today or dt.date.today()
    earliest = today - dt.timedelta(days=HOMEWORK_PAST_DAYS)
    latest = today + dt.timedelta(days=HOMEWORK_FUTURE_DAYS)

    records: list[HomeworkRecord] = []
    for lesson in _attr(day, "lessons", []) or []:
        subject = str(_attr(lesson, "subject", "") or "—")
        lesson_number = _attr(lesson, "number")

        for index, assignment in enumerate(_attr(lesson, "assignments", []) or []):
            raw_content = _attr(assignment, "content", "") or ""
            text = clean_content(raw_content)
            attachments = _attachments(assignment)
            # «---Не указана---» означает «задание есть, текста нет».
            explicitly_empty = str(raw_content).strip() in {"---Не указана---", "Не указана"}
            if not text and not attachments and not explicitly_empty:
                continue

            due = _as_date(_attr(assignment, "deadline")) or day_date
            if not earliest <= due <= latest:
                continue

            records.append(
                HomeworkRecord(
                    subject=subject,
                    due_date=due,
                    assignment_type=str(
                        _attr(assignment, "kind") or _attr(assignment, "type") or "Задание"
                    ).strip(),
                    text=text or ("Не указана" if explicitly_empty else ""),
                    lesson_number=lesson_number or (index + 1),
                    attachments=attachments,
                )
            )
    return records


def _attachments(assignment: Any) -> tuple[Attachment, ...]:
    result: list[Attachment] = []
    for item in _attr(assignment, "attachments", []) or []:
        att_id = _attr(item, "id")
        name = _attr(item, "name") or (f"file_{att_id}" if att_id is not None else "Вложение")
        result.append(
            Attachment(id=int(att_id) if att_id is not None else None, name=str(name))
        )
    return tuple(result)


def diary_days(days: list[Any], *, today: dt.date | None = None) -> list[DiaryDay]:
    """Собрать дни дневника с оценками и домашними заданиями."""
    result: list[DiaryDay] = []
    for day in days:
        day_date = _as_date(_attr(day, "day"))
        if day_date is None:
            continue
        result.append(
            DiaryDay(
                day=day_date,
                marks=marks_from_day(day),
                homework=homework_from_day(day, today=today),
            )
        )
    result.sort(key=lambda d: d.day)
    return result


def students_from_diary_init(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    """Разобрать список детей из ответа `student/diary/init`.

    Сервер отдаёт `students` то словарём, то списком — обе формы встречаются
    в проде, поэтому поддерживаем обе.
    """
    raw = payload.get("students") or {}
    current_id = _safe_int(payload.get("currentStudentId"))

    if isinstance(raw, dict):
        items: list[tuple[Any, Any]] = list(raw.items())
    elif isinstance(raw, list):
        items = list(enumerate(raw))
    else:
        items = []

    students: list[dict[str, Any]] = []
    for key, student in items:
        if not isinstance(student, dict):
            continue
        student_id = _safe_int(student.get("studentId")) or _safe_int(key)
        if student_id is None:
            continue
        name = next(
            (
                str(student[field]).strip()
                for field in ("fio", "fullName", "name")
                if str(student.get(field) or "").strip()
            ),
            f"Ученик {student_id}",
        )
        students.append({"id": student_id, "name": name})

    if current_id is None and students:
        current_id = students[0]["id"]
    return students, current_id


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
