"""Сбор, фильтрация и текстовый рендер оценок, домашних заданий и расписания."""

import html
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

from ..config import CHECK_INTERVAL, NETSCHOOL_CACHE_DIR
from ..storage import (
    _clamp_interval,
    _get_available_students,
    _get_user_ns_school,
    _get_user_ns_url,
    format_user_quiet_hours,
    get_user_exclude_titles,
    get_user_student_name,
    get_user_subject_include_titles,
    is_subject_allowed_for_user,
)
from ..utils import (
    _clean_assignment_content,
    _next_three_days,
    _current_quarter_start,
    _extract_mark_value,
    _file_count_label,
    _format_assignment_title,
    _format_date_label,
    _mark_to_int,
    _normalize_subject,
    _normalize_title,
    _parse_mark_value,
)

logger = logging.getLogger("netschoolbot")


def _iter_grade_entries(
    days: list[Any],
    start_date: Optional[datetime.date] = None,
    end_date: Optional[datetime.date] = None,
    include_subjects: Optional[Set[str]] = None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for day in days:
        current_day = getattr(day, "day", None)
        if not current_day:
            continue
        if start_date and current_day < start_date:
            continue
        if end_date and current_day > end_date:
            continue
        for lesson in getattr(day, "lessons", []) or []:
            subject = getattr(lesson, "subject", "") or "—"
            if include_subjects and _normalize_subject(subject) not in include_subjects:
                continue
            for assignment in getattr(lesson, "assignments", []) or []:
                mark_value = _extract_mark_value(assignment)
                if mark_value is None:
                    continue
                entries.append({
                    "date": current_day,
                    "subject": subject,
                    "title": (getattr(assignment, "kind", None) or getattr(assignment, "type", None) or "Задание").strip(),
                    "mark": mark_value,
                    "mark_int": _mark_to_int(mark_value),
                    "weight": getattr(assignment, "weight", None) or 1,
                })
    return entries

def _collect_grades(
    days: list[Any],
    since_date: Optional[datetime.date] = None
) -> tuple[list[str], list[tuple[str, datetime.date, str, Any, int]]]:
    subjects: list[str] = []
    entries: list[tuple[str, datetime.date, str, Any, int]] = []
    for day in days:
        if since_date and day.day < since_date:
            # пропускаем дни до начала текущей четверти
            for lesson in day.lessons:
                subject = lesson.subject
                if subject and subject not in subjects:
                    subjects.append(subject)
            continue
        for lesson in day.lessons:
            subject = lesson.subject
            if subject and subject not in subjects:
                subjects.append(subject)
            for assignment in lesson.assignments:
                mark_value = _extract_mark_value(assignment)
                if mark_value is None:
                    continue
                title = (assignment.kind or "Задание").strip()
                entries.append((subject, day.day, title, mark_value, assignment.weight or 1))
    return subjects, entries

def _render_grades_text(subject_title: str, filtered: list[tuple[str, datetime.date, str, Any, int]]) -> str:
    filtered.sort(key=lambda x: x[1])
    lines = [f"📋 Оценки по предмету {subject_title}:"]
    max_len = 3500
    reserved = 120
    total = 0.0
    weight_sum = 0.0
    count = 0

    for _, day, title, mark, weight in filtered:
        line = f"• {day.strftime('%d.%m')}: {title} — {mark} (вес {weight})"
        if sum(len(x) for x in lines) + len(line) + 1 > max_len - reserved:
            remaining = len(filtered) - (len(lines) - 1)
            lines.append(f"…и еще {remaining} оценок")
            break
        lines.append(line)

        value = _parse_mark_value(mark)
        if value is not None:
            w = weight if weight and weight > 0 else 1
            total += value * w
            weight_sum += w
            count += 1

    if count > 0 and weight_sum > 0:
        average = total / weight_sum
        lines.append("")
        lines.append(f"Всего оценок: {count}")
        lines.append(f"Средний балл: {average:.2f}")

    return "\n".join(lines)

def _render_homework_text(
    days: list[Any],
    target_dates: set,
    header: str,
    attach_map: Optional[dict] = None
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """
    attach_map: {assignment.id: [{"id":..., "name":..., "subject":...}, ...]}
    Если передан, используется вместо assignment.attachments.
    """
    items: list[tuple] = []
    attachments: list[dict[str, Any]] = []
    seen_attach_ids: set[int] = set()
    for day in days:
        for lesson in day.lessons:
            for assignment in lesson.assignments:
                content = _clean_assignment_content(assignment.content or "")
                deadline = assignment.deadline or day.day
                # Убираем фильтрацию по прошедшим датам - разрешаем просмотр истории
                if deadline not in target_dates:
                    continue
                # Показываем только содержание задания, без префикса типа
                title = content if content else (assignment.kind or "Задание").strip()
                # Определяем вложения: сначала из attach_map, потом из assignment.attachments
                if attach_map is not None:
                    fetched = attach_map.get(assignment.id) or []
                    n_files = len(fetched)
                    for a in fetched:
                        if a["id"] not in seen_attach_ids:
                            seen_attach_ids.add(a["id"])
                            attachments.append(a)
                else:
                    raw_list = list(getattr(assignment, "attachments", []) or [])
                    n_files = len(raw_list)
                    for att in raw_list:
                        if att.id not in seen_attach_ids:
                            seen_attach_ids.add(att.id)
                            attachments.append({"id": att.id, "name": att.name, "subject": lesson.subject})
                if n_files:
                    title += f" ({_file_count_label(n_files)})"
                items.append((deadline, lesson.subject, title))
    if not items:
        return None, []
    items.sort(key=lambda x: (x[0], x[1]))
    lines = [header]
    for deadline, subject, title in items:
        lines.append(f"• {deadline.strftime('%d.%m')} — {subject}: {title}")
    return "\n".join(lines), attachments

def _render_schedule_text(days: list[Any], target_dates: set[datetime.date], header: str) -> Optional[str]:
    weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    filtered_days = [day for day in days if day.lessons and day.day in target_dates]
    filtered_days.sort(key=lambda d: d.day)
    if not filtered_days:
        return None
    lines = [header]
    for day in filtered_days:
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
            lines.append(f"{idx}. {time_range} {lesson.subject}{room}".strip())
    return "\n".join(lines)

def _build_mystats_text(user_data: Dict[str, Any], entries: list[dict[str, Any]], student_name: str = "") -> str:
    numeric = [e for e in entries if e.get("mark_int") is not None]
    if not numeric:
        return "📊 <b>Моя статистика</b>\n\nНет числовых оценок за текущую четверть."

    counts = Counter(int(e["mark_int"]) for e in numeric)
    subject_map: Dict[str, list[int]] = {}
    for item in numeric:
        subject_map.setdefault(item["subject"], []).append(int(item["mark_int"]))
    subject_lines = []
    for subject, marks in sorted(subject_map.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True)[:6]:
        avg = sum(marks) / len(marks)
        subject_lines.append(f"• {html.escape(subject)} — ср. {avg:.2f}, оценок: {len(marks)}")

    average = sum(int(e["mark_int"]) for e in numeric) / len(numeric)
    student_name = html.escape(student_name or user_data.get("student_name") or user_data.get("display_name") or "")
    lines = [
        "📊 <b>Моя статистика</b>",
        "",
    ]
    if student_name:
        lines.append(f"👤 {student_name}")
    lines.extend([
        f"• Средний балл: <b>{average:.2f}</b>",
        f"• Всего оценок: <b>{len(numeric)}</b>",
        f"• 5: {counts.get(5, 0)} | 4: {counts.get(4, 0)} | 3: {counts.get(3, 0)} | 2: {counts.get(2, 0)}",
        "",
        "<b>Лучшие предметы:</b>",
        *(subject_lines or ["• Пока недостаточно данных"]),
    ])
    return "\n".join(lines)

def _build_weeksummary_text(user_data: Dict[str, Any], entries: list[dict[str, Any]], start_date: datetime.date, end_date: datetime.date) -> str:
    if not entries:
        return (
            "🗓 <b>Недельная сводка</b>\n\n"
            f"За период {start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m')} новых оценок не найдено."
        )

    numeric = [e for e in entries if e.get("mark_int") is not None]
    counts = Counter(int(e["mark_int"]) for e in numeric)
    by_subject = Counter(e["subject"] for e in entries)
    recent = sorted(entries, key=lambda x: x["date"], reverse=True)[:5]
    lines = [
        "🗓 <b>Недельная сводка</b>",
        "",
        f"Период: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}",
        f"• Оценок за неделю: <b>{len(entries)}</b>",
    ]
    if numeric:
        avg = sum(int(e["mark_int"]) for e in numeric) / len(numeric)
        lines.append(f"• Средний балл недели: <b>{avg:.2f}</b>")
        lines.append(f"• 5: {counts.get(5, 0)} | 4: {counts.get(4, 0)} | 3: {counts.get(3, 0)} | 2: {counts.get(2, 0)}")
    lines.extend([
        "",
        "<b>По предметам:</b>",
        *[f"• {html.escape(subject)} — {count}" for subject, count in by_subject.most_common(6)],
        "",
        "<b>Последние оценки:</b>",
        *[
            f"• {item['date'].strftime('%d.%m')} — {html.escape(item['subject'])}: {item['mark']}"
            for item in recent
        ],
    ])
    return "\n".join(lines)

def _build_profile_text(user_data: Dict[str, Any], user_id: int) -> str:
    subject_filters = user_data.get("subject_filters", {}).get("include") or []
    quiet_hours = format_user_quiet_hours(user_data)
    weekly = "включена ✅" if user_data.get("weekly_summary_enabled") else "выключена 🔕"
    student_name = html.escape(get_user_student_name(user_id) or user_data.get("display_name") or f"ID {user_id}")
    school = html.escape(str(_get_user_ns_school(user_data) or "—"))
    url = html.escape(str(_get_user_ns_url(user_data) or "—"))
    interval = _clamp_interval(int(user_data.get("check_interval") or CHECK_INTERVAL))
    return (
        "👤 <b>Профиль NetSchool</b>\n\n"
        f"• Ученик: {student_name}\n"
        f"• Доступно детей: {len(_get_available_students(user_data))}\n"
        f"• Школа: {school}\n"
        f"• URL: {url}\n"
        f"• Уведомления: {'включены ✅' if user_data.get('enabled') else 'выключены 🔕'}\n"
        f"• Интервал: {interval // 60} мин\n"
        f"• Сводка по понедельникам: {weekly}\n"
        f"• Тихие часы: {quiet_hours}\n"
        f"• Фильтр типов: {', '.join(user_data.get('filters', {}).get('exclude') or []) or 'нет'}\n"
        f"• Фильтр предметов: {', '.join(subject_filters) or 'все предметы'}"
    )

def _netschool_cache_path(user_id: int) -> Path:
    return NETSCHOOL_CACHE_DIR / f"cache_{user_id}.json"

def _load_netschool_cache(user_id: int) -> dict:
    path = _netschool_cache_path(user_id)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _save_netschool_cache(user_id: int, data: dict) -> None:
    path = _netschool_cache_path(user_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _refresh_user_cache_from_days(user_id: int, days: list[Any]) -> None:
    quarter_start = _current_quarter_start()
    subjects, entries = _collect_grades(days, since_date=quarter_start)
    subjects_sorted = sorted(subjects)
    by_subject: Dict[str, str] = {}
    for subject in subjects_sorted:
        subject_norm = _normalize_subject(subject)
        filtered = [e for e in entries if _normalize_subject(e[0]) == subject_norm]
        if not filtered:
            continue
        by_subject[subject_norm] = _render_grades_text(subject, filtered)

    today = datetime.now(dt_timezone(timedelta(hours=3))).date()
    target_dates = set(_next_three_days(today))
    homework_text, _ = _render_homework_text(days, target_dates, "📚 Домашнее задание (ближайшие 3 дня):")
    schedule_text = _render_schedule_text(days, target_dates, "🗓 Расписание на ближайшие 3 дня:")

    cache = _load_netschool_cache(user_id)
    cache["grades"] = {
        "subjects": subjects_sorted,
        "by_subject": by_subject,
        "updated_at": datetime.now().isoformat()
    }
    if homework_text:
        cache["homework"] = {
            "text": homework_text,
            "dates": [d.isoformat() for d in sorted(target_dates)],
            "updated_at": datetime.now().isoformat()
        }
    if schedule_text:
        cache["schedule"] = {
            "text": schedule_text,
            "dates": [d.isoformat() for d in sorted(target_dates)],
            "updated_at": datetime.now().isoformat()
        }
    _save_netschool_cache(user_id, cache)

