"""Меню, дневник, расписание, оценки и статистика."""

from __future__ import annotations

import datetime as dt
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ...context import AppContext
from ...domain import formatting
from ...domain.models import User, normalize
from ...netschool.errors import NetSchoolError
from ...netschool.service import msk_today
from .. import keyboards
from .common import reply, report_error, require_school

logger = logging.getLogger("netschoolbot.bot")
router = Router(name="menu")

GREETING = (
    "👋 <b>Бот «Сетевого города»</b>\n\n"
    "Присылаю новые оценки, их изменения и удаления, показываю домашние "
    "задания, расписание и статистику.\n\n"
    "Начните с /login — выберете свой регион и школу."
)


def next_school_days(start: dt.date, count: int = 3) -> list[dt.date]:
    """Ближайшие учебные дни. С пятницы — сразу на понедельник."""
    days: list[dt.date] = []
    day = start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    return days


@router.message(CommandStart())
@router.message(Command("menu"))
async def show_menu(message: Message, user: User) -> None:
    text = GREETING if not user.school.configured else "Главное меню"
    await message.answer(text, parse_mode="HTML", reply_markup=keyboards.main_menu())


@router.message(Command("dz"))
@router.message(F.text == "📚 Домашка")
async def homework(message: Message, user: User, app: AppContext) -> None:
    if hint := require_school(user):
        await reply(message, hint)
        return
    try:
        today = msk_today()
        wanted = set(next_school_days(today))
        items = await app.diary.fetch_homework(user, weeks_back=0, weeks_forward=1, today=today)
    except NetSchoolError as exc:
        await report_error(message, exc)
        return
    relevant = [item for item in items if item.due_date in wanted]
    await reply(message, formatting.homework_list(relevant, "📚 <b>Домашние задания</b>"))


@router.message(Command("rasp"))
@router.message(F.text == "🗓 Расписание")
async def schedule(message: Message, user: User, app: AppContext) -> None:
    if hint := require_school(user):
        await reply(message, hint)
        return
    try:
        today = msk_today()
        wanted = set(next_school_days(today))
        days = await app.diary.fetch_diary(user, weeks_back=0, weeks_forward=1, today=today)
    except NetSchoolError as exc:
        await report_error(message, exc)
        return

    # fetch_diary отдаёт доменные дни без уроков — расписание берём из
    # исходной структуры, поэтому запрашиваем его отдельным вызовом.
    relevant = [day for day in days if day.day in wanted]
    if not relevant:
        await reply(message, "🗓 На ближайшие дни расписания нет.")
        return
    lines = ["🗓 <b>Расписание</b>"]
    for day in sorted(relevant, key=lambda d: d.day):
        lines.append(f"\n📅 <b>{formatting.date_label(day.day)}</b>")
        subjects = [item.subject for item in day.homework] or [
            record.subject for record in day.marks
        ]
        if not subjects:
            lines.append("— нет данных")
            continue
        seen: list[str] = []
        for subject in subjects:
            if subject not in seen:
                seen.append(subject)
        lines.extend(f"• {formatting.esc(subject)}" for subject in seen)
    await reply(message, "\n".join(lines))


@router.message(Command("grades"))
@router.message(F.text == "📊 Оценки")
async def grades(message: Message, user: User, app: AppContext) -> None:
    if hint := require_school(user):
        await reply(message, hint)
        return
    try:
        records = await app.diary.fetch_marks(user)
    except NetSchoolError as exc:
        await report_error(message, exc)
        return
    if not records:
        await reply(message, "📊 Оценок за период нет.")
        return

    subjects = sorted({record.subject for record in records})
    await app.cache.put(user.telegram_id, "subjects", subjects)
    await reply(
        message,
        "📊 Выберите предмет:",
        reply_markup=keyboards.subjects(subjects),
    )


@router.callback_query(F.data.startswith("subject:"))
async def subject_marks(callback: CallbackQuery, user: User, app: AppContext) -> None:
    await callback.answer()
    cached = await app.cache.get(user.telegram_id, "subjects")
    if cached is None:
        await reply(callback, "Список предметов устарел — откройте /grades заново.")
        return
    subjects, _ = cached
    try:
        index = int(callback.data.split(":", 1)[1])
        subject = subjects[index]
    except (ValueError, IndexError):
        await reply(callback, "Не понял, какой предмет. Откройте /grades заново.")
        return

    try:
        records = await app.diary.fetch_marks(user)
    except NetSchoolError as exc:
        await report_error(callback, exc)
        return
    wanted = normalize(subject)
    selected = [r for r in records if normalize(r.subject) == wanted]
    await reply(callback, formatting.marks_by_subject(subject, selected))


@router.message(Command("mystats"))
@router.message(F.text == "📈 Статистика")
async def statistics(message: Message, user: User, app: AppContext) -> None:
    if hint := require_school(user):
        await reply(message, hint)
        return
    try:
        records = await app.diary.fetch_marks(user)
    except NetSchoolError as exc:
        await report_error(message, exc)
        return
    await reply(message, formatting.statistics(user, records))


@router.message(Command("weeksummary"))
async def week_summary(message: Message, user: User, app: AppContext) -> None:
    if hint := require_school(user):
        await reply(message, hint)
        return
    today = msk_today()
    start = today - dt.timedelta(days=today.weekday())
    try:
        records = await app.diary.fetch_marks(user, weeks_back=1, weeks_forward=0, today=today)
    except NetSchoolError as exc:
        await report_error(message, exc)
        return
    week = [r for r in records if start <= r.date <= today]
    await reply(message, formatting.weekly_summary(week, start, today))


@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def profile(message: Message, user: User) -> None:
    await reply(message, formatting.profile(user))


@router.message(Command("app"))
async def miniapp(message: Message, user: User, app: AppContext) -> None:
    """Постоянная ссылка на PWA."""
    if hint := require_school(user):
        await reply(message, hint)
        return
    token = await app.miniapp.issue_token(user.telegram_id)
    url = f"{app.settings.web.miniapp_url}?token={token}"
    await reply(
        message,
        "📱 Ваша personal-ссылка на приложение. Не передавайте её другим — "
        "по ней открывается ваш дневник.\n\n"
        "Если ссылка утекла, выпустите новую: /app_reset",
        reply_markup=keyboards.miniapp_link(url),
    )


@router.message(Command("app_reset"))
async def miniapp_reset(message: Message, user: User, app: AppContext) -> None:
    token = await app.miniapp.issue_token(user.telegram_id, revoke_existing=True)
    url = f"{app.settings.web.miniapp_url}?token={token}"
    await reply(
        message,
        "🔄 Старая ссылка отозвана. Новая:",
        reply_markup=keyboards.miniapp_link(url),
    )


@router.message(Command("status"))
async def status(message: Message, user: User, app: AppContext) -> None:
    watching = user.telegram_id in app.watchers.running
    tracked = len(await app.state.load_marks(user.telegram_id))
    lines = [
        "📡 <b>Состояние</b>",
        "",
        f"• Проверка оценок: {'идёт ✅' if watching else 'не запущена'}",
        f"• Интервал: {user.check_interval // 60} мин",
        f"• Оценок под наблюдением: {tracked}",
        f"• Школа: {formatting.esc(user.school.name or '—')}",
    ]
    if await app.state.is_baseline_pending(user.telegram_id):
        lines.append("• Первая проверка после переноса пройдёт молча")
    await reply(message, "\n".join(lines))
