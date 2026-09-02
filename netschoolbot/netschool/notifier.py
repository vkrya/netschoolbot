"""GradeNotifier — мониторинг оценок, домашних заданий и почты.

Используется в двух режимах:
  * персональный (user_id задан) — уведомления в ЛС конкретному пользователю;
  * общий (user_id=None) — чекер КР/СР/лабораторных в групповой чат.
"""

import asyncio
import html
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from netschoolpy import NetSchool
import netschoolpy.exceptions as netschoolpy_exceptions

from ..config import ERROR_NOTIFICATIONS_ENABLED, data_path
from ..bot.esia import _make_esia_mfa_callback
from ..bot.factory import create_tg_bot
from ..bot.keyboards import (
    _build_grade_feedback_keyboard,
    _kb_bulk_choice,
    _kb_events_choice,
    _kb_homework_choice,
)
from ..storage import (
    _default_exclude_titles,
    _ensure_grade_feedback_entry,
    _build_grade_feedback_id,
    _save_grade_feedback_store,
    _send_netschool_web_push,
    _should_send_telegram,
    get_netschool_user,
    get_user_subject_include_titles,
    is_subject_allowed_for_user,
    is_user_quiet_hours_now,
    save_netschool_users,
)
from ..utils import (
    _clean_assignment_content,
    _extract_mark_value,
    _msk_tz,
    _normalize_title,
    now_msk,
    write_json_atomic,
)
from .client import (
    _apply_selected_student_to_client,
    _close_netschool_client,
    _close_netschool_session_for_user,
    _fetch_days_for_period,
    _fetch_student_name,
    _make_netschool,
    _netschool_session_is_alive,
    _save_netschool_session,
    _sync_user_students_from_ns,
    _try_restore_netschool_session,
    is_netschool_auth_error,
    is_server_unavailable_error,
)
from .grades import (
    _build_weeksummary_text,
    _iter_grade_entries,
    _refresh_user_cache_from_days,
)

logger = logging.getLogger("netschoolbot")


class GradeNotifier:
    """Класс для мониторинга и отправки уведомлений о новых оценках"""
    
    def __init__(
        self,
        netschool_url: str,
        netschool_login: str,
        netschool_password: str,
        netschool_school: str,
        telegram_token: str,
        telegram_chat_id: str,
        check_interval: int = 300,
        bot: Optional[Bot] = None,
        log_bot: Optional[Bot] = None,
        admin_id: Optional[int] = None,
        user_id: Optional[int] = None,
        user_display_name: Optional[str] = None,
        exclude_titles: Optional[Set[str]] = None,
        sent_grades_file: Optional[str] = None,
        known_grades_file: Optional[str] = None,
        known_homework_file: Optional[str] = None,
        message_thread_id: Optional[int] = None,
        login_type: str = "password",
    ):
        self.netschool_url = netschool_url
        self.netschool_login = netschool_login
        self.netschool_password = netschool_password
        self.netschool_school = netschool_school
        self.login_type = login_type
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.check_interval = check_interval
        self.message_thread_id = message_thread_id
        self.user_id = user_id
        self.user_display_name = user_display_name or ""
        self.exclude_titles = exclude_titles or set(_default_exclude_titles())
        self.track_changes = self.user_id is not None
        self.include_mark = self.user_id is not None

        if self.user_display_name:
            safe_name = html.escape(self.user_display_name)
            self.student_line = f"<b>Ученик:</b> {safe_name}\n"
        else:
            self.student_line = ""
        
        # Файл для хранения уже отправленных оценок
        self.sent_grades_file = sent_grades_file or str(data_path('sent_grades.json'))
        self.sent_grades: Set[str] = self._load_sent_grades()

        self.known_grades_file = known_grades_file
        self.known_grades: Dict[str, Any] = {}
        self._known_grades_initialized = False
        if self.track_changes and self.known_grades_file:
            self.known_grades = self._load_known_grades()
        self.known_homework_file = known_homework_file
        self.known_homework: Dict[str, Any] = {}
        self._known_homework_initialized = False
        if self.track_changes and self.known_homework_file:
            self.known_homework = self._load_known_homework()
        
        # Telegram бот (aiogram)
        # Если передан существующий бот, используем его
        self.bot = bot or create_tg_bot(self.telegram_token)
        self._owns_bot = bot is None
        
        # Бот для логов и ID админа
        self.log_bot = log_bot
        self.admin_id = admin_id
        
        # Клиент NetSchool (сохраняем сессию)
        self.ns = _make_netschool(self.netschool_url)
        self._session_active = False
        
        # Cooldown для уведомлений об ошибках (5 минут)
        self._last_error_notification = 0
        self._error_notification_cooldown = 300

    async def _reset_netschool_session(self, clear_saved: bool = False) -> None:
        self._session_active = False
        if self.user_id is not None:
            await _close_netschool_session_for_user(self.user_id, clear_saved=clear_saved)
        else:
            await _close_netschool_client(self.ns, do_logout=False)
        self.ns = _make_netschool(self.netschool_url)

    def _get_user_data(self) -> Dict[str, Any]:
        if self.user_id is None:
            return {}
        return get_netschool_user(self.user_id)

    def _subject_allowed(self, subject: str) -> bool:
        if self.user_id is None:
            return True
        return is_subject_allowed_for_user(self._get_user_data(), subject)

    def _quiet_hours_active(self) -> bool:
        if self.user_id is None:
            return False
        return is_user_quiet_hours_now(self._get_user_data())

    async def _maybe_send_weekly_summary(self) -> None:
        if self.user_id is None:
            return
        user_data = self._get_user_data()
        if not user_data.get("weekly_summary_enabled"):
            return
        if self._quiet_hours_active():
            return
        msk_now = datetime.now(dt_timezone(timedelta(hours=3)))
        if msk_now.weekday() != 0 or msk_now.hour < 7:
            return
        week_key = f"{msk_now.isocalendar().year}-W{msk_now.isocalendar().week}"
        if user_data.get("last_weekly_summary") == week_key:
            return

        end_date = msk_now.date() - timedelta(days=1)
        start_date = end_date - timedelta(days=6)
        include_subjects = get_user_subject_include_titles(user_data)
        days = await _fetch_days_for_period(self.ns, start_date, end_date)
        entries = _iter_grade_entries(days, start_date=start_date, end_date=end_date, include_subjects=include_subjects)
        text = _build_weeksummary_text(user_data, entries, start_date, end_date)
        push_sent = await _send_netschool_web_push(
            self.user_id,
            user_data,
            "NetSchool: недельная сводка",
            f"Сводка за {start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m')}",
            "grades",
        )
        telegram_sent = False
        if _should_send_telegram(user_data):
            await self.bot.send_message(
                chat_id=self.telegram_chat_id,
                text=text,
                parse_mode="HTML",
                message_thread_id=self.message_thread_id,
            )
            telegram_sent = True
        if not (push_sent or telegram_sent):
            return
        user_data["last_weekly_summary"] = week_key
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()

    async def _check_mail_updates(self) -> None:
        if not self.user_id:
            return
        user_data = get_netschool_user(self.user_id)
        if not user_data.get("notify_mail", True):
            return
        try:
            unread_ids = await self.ns.mail_unread()
            seen = set(user_data.get("mail_seen_ids") or [])
            new_ids = [mid for mid in unread_ids if mid not in seen]
            if not new_ids:
                return
            for mid in new_ids[:5]:
                mail = await self.ns.mail_read(mid)
                sent = mail.sent.strftime("%d.%m.%Y %H:%M")
                subject = mail.subject or "(без темы)"
                author = mail.author_name or "—"
                text = (
                    "📬 <b>Новое письмо</b>\n"
                    f"<b>Тема:</b> {html.escape(subject)}\n"
                    f"<b>От:</b> {html.escape(author)}\n"
                    f"<b>Дата:</b> {sent}"
                )
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Открыть", callback_data=f"mail_read:{mid}")]
                ])
                push_sent = await _send_netschool_web_push(
                    self.user_id,
                    user_data,
                    "NetSchool: новое письмо",
                    f"{subject} · {author}",
                    "mail",
                )
                telegram_sent = False
                if _should_send_telegram(user_data):
                    await self.bot.send_message(
                        chat_id=self.telegram_chat_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=keyboard,
                        message_thread_id=self.message_thread_id
                    )
                    telegram_sent = True
                if push_sent or telegram_sent:
                    seen.add(mid)
            user_data["mail_seen_ids"] = list(seen)[-200:]
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
        except Exception as e:
            logger.warning(f"Ошибка проверки почты NetSchool: {e}")
    
    def _load_sent_grades(self) -> Set[str]:
        """Загрузить список уже отправленных оценок из файла"""
        if os.path.exists(self.sent_grades_file):
            try:
                with open(self.sent_grades_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(data.get('grades', []))
            except Exception as e:
                logger.error(f"Ошибка при загрузке sent_grades.json: {e}")
                return set()
        return set()
    
    def _save_sent_grades(self):
        """Сохранить список отправленных оценок в файл"""
        try:
            write_json_atomic(self.sent_grades_file, {'grades': list(self.sent_grades)})
        except Exception as e:
            logger.error(f"Ошибка при сохранении sent_grades.json: {e}")

    def _load_known_grades(self) -> Dict[str, Any]:
        """Загрузить известные оценки (для отслеживания изменений/удалений)"""
        if not self.known_grades_file:
            return {}
        if os.path.exists(self.known_grades_file):
            self._known_grades_initialized = True
            try:
                with open(self.known_grades_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data.get("grades", {}) if "grades" in data else data
            except Exception as e:
                logger.error(f"Ошибка при загрузке known_grades.json: {e}")
                return {}
        return {}

    def _save_known_grades(self):
        """Сохранить известные оценки"""
        if not self.known_grades_file:
            return
        try:
            write_json_atomic(self.known_grades_file, {"grades": self.known_grades})
        except Exception as e:
            logger.error(f"Ошибка при сохранении known_grades.json: {e}")

    def _load_known_homework(self) -> Dict[str, Any]:
        if not self.known_homework_file:
            return {}
        if os.path.exists(self.known_homework_file):
            self._known_homework_initialized = True
            try:
                with open(self.known_homework_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data.get("homework", {}) if "homework" in data else data
            except Exception as e:
                logger.error(f"Ошибка при загрузке known_homework.json: {e}")
                return {}
        return {}

    def _save_known_homework(self):
        if not self.known_homework_file:
            return
        try:
            write_json_atomic(self.known_homework_file, {"homework": self.known_homework})
            self._known_homework_initialized = True
        except Exception as e:
            logger.error(f"Ошибка при сохранении known_homework.json: {e}")
    
    def _create_grade_id(self, assignment: Dict[str, Any]) -> str:
        """Создать уникальный идентификатор для оценки"""
        # NetSchool API возвращает assignment.id = 0 для всех оценок
        # Поэтому используем комбинацию: название, предмет, дата, оценка
        # И добавляем хеш от содержимого для дополнительной уникальности
        
        assignment_name = assignment.get('assignmentName', '')
        subject = assignment.get('subjectName', '')
        date = assignment.get('date', '')
        mark_value = assignment.get('mark', {}).get('value', '')
        lesson_number = assignment.get('lessonNumber', '')
        lesson_start = assignment.get('lessonStart', '')
        lesson_end = assignment.get('lessonEnd', '')
        comment = assignment.get('comment', '')
        assignment_index = assignment.get('assignmentIndex', '')
        
        # Создаем базовый ID
        base_id = f"{assignment_name}_{subject}_{date}_{mark_value}_{lesson_number}_{lesson_start}_{lesson_end}_{comment}_{assignment_index}"
        
        return base_id

    def _create_assignment_key(self, assignment: Dict[str, Any]) -> str:
        """Создать ключ задания без учета оценки (для отслеживания изменений/удалений)"""
        assignment_name = assignment.get('assignmentName', '')
        subject = assignment.get('subjectName', '')
        date = assignment.get('date', '')
        lesson_number = assignment.get('lessonNumber', '')
        lesson_start = assignment.get('lessonStart', '')
        lesson_end = assignment.get('lessonEnd', '')
        comment = assignment.get('comment', '')
        assignment_index = assignment.get('assignmentIndex', '')
        base_id = f"{assignment_name}_{subject}_{date}_{lesson_number}_{lesson_start}_{lesson_end}_{comment}_{assignment_index}"
        return base_id

    def _create_assignment_key_loose(self, assignment: Dict[str, Any]) -> str:
        """Ключ задания без индекса (для подтверждения удаления)"""
        assignment_name = assignment.get('assignmentName', '')
        subject = assignment.get('subjectName', '')
        date = assignment.get('date', '')
        lesson_number = assignment.get('lessonNumber', '')
        lesson_start = assignment.get('lessonStart', '')
        lesson_end = assignment.get('lessonEnd', '')
        comment = assignment.get('comment', '')
        return f"{assignment_name}_{subject}_{date}_{lesson_number}_{lesson_start}_{lesson_end}_{comment}"

    def _build_homework_payload(self, day: Any, lesson: Any, assignment: Any, assignment_index: int) -> Optional[Dict[str, Any]]:
        raw_content = getattr(assignment, 'content', '') or ''
        text = _clean_assignment_content(raw_content)
        raw_attachments = list(getattr(assignment, 'attachments', []) or [])
        attachments: list[dict[str, Any]] = []
        for attachment in raw_attachments:
            att_id = getattr(attachment, 'id', None)
            att_name = getattr(attachment, 'name', None) or (f"file_{att_id}" if att_id is not None else "Вложение")
            attachments.append({
                "id": int(att_id) if att_id is not None else None,
                "name": str(att_name),
            })

        unspecified = str(raw_content).strip() in {"---Не указана---", "Не указана"}
        if not text and not attachments and not unspecified:
            return None

        due_date = getattr(assignment, 'deadline', None) or getattr(day, 'day', None)
        if not due_date:
            return None
        today = datetime.now(dt_timezone(timedelta(hours=3))).date()
        if due_date < today - timedelta(days=1) or due_date > today + timedelta(days=30):
            return None

        assignment_type = (getattr(assignment, 'kind', None) or getattr(assignment, 'type', None) or 'Задание').strip()
        lesson_number = getattr(lesson, 'number', None) or (assignment_index + 1)
        lesson_start = getattr(lesson, 'start', None)
        lesson_end = getattr(lesson, 'end', None)
        return {
            "assignmentType": assignment_type,
            "subjectName": getattr(lesson, 'subject', '') or 'Не указан',
            "date": due_date.strftime('%Y-%m-%d'),
            "text": text or ("Не указана" if unspecified else ""),
            "lessonNumber": lesson_number,
            "lessonStart": lesson_start.strftime('%H:%M') if hasattr(lesson_start, 'strftime') else '',
            "lessonEnd": lesson_end.strftime('%H:%M') if hasattr(lesson_end, 'strftime') else '',
            "assignmentIndex": assignment_index,
            "attachments": attachments,
            "attachmentsCount": len(attachments),
        }

    def _create_homework_key(self, homework: Dict[str, Any]) -> str:
        attachment_key = "|".join(
            f"{item.get('id') or ''}:{item.get('name') or ''}"
            for item in sorted(homework.get('attachments') or [], key=lambda item: (str(item.get('id') or ''), str(item.get('name') or '')))
        )
        return "_".join([
            str(homework.get('subjectName', '')),
            str(homework.get('date', '')),
            str(homework.get('lessonNumber', '')),
            str(homework.get('assignmentType', '')),
            str(homework.get('text', '')),
            attachment_key,
        ])

    async def _fetch_all_days(self, start_monday: datetime.date, end_date: datetime.date) -> list[Any]:
        """Получить все дни из дневника по неделям."""
        all_days: list[Any] = []
        current_date = start_monday
        today = datetime.now(dt_timezone(timedelta(hours=3))).date()
        while current_date <= end_date:
            try:
                diary = await self.ns.diary(start=current_date)
                if getattr(diary, "schedule", None):
                    for day in diary.schedule:
                        if not any(d.day == day.day for d in all_days):
                            all_days.append(day)
                current_date = current_date + timedelta(days=7)
            except Exception as e:
                err_text = str(e or "")
                # Некоторые школы возвращают 409 для будущих недель — прекращаем цикл,
                # чтобы не засыпать логи повторяющимися ошибками.
                if current_date > today and "409" in err_text:
                    logger.info(f"Остановлен запрос будущих недель на {current_date}: {e}")
                    break
                logger.warning(f"Ошибка при запросе недели с {current_date}: {e}")
                current_date = current_date + timedelta(days=7)
                continue
        return all_days

    def _build_current_grades_map(self, all_days: list[Any]) -> Dict[str, Dict[str, Any]]:
        """Построить карту оценок без уведомлений (для проверки удаления)."""
        current_grades: Dict[str, Dict[str, Any]] = {}
        for day in all_days:
            for lesson in day.lessons:
                if not self._subject_allowed(lesson.subject):
                    continue
                for assign_idx, assignment in enumerate(lesson.assignments):
                    mark_value = _extract_mark_value(assignment)

                    if mark_value is None or (isinstance(mark_value, str) and mark_value == ""):
                        continue

                    assign_type = getattr(assignment, 'kind', None) or getattr(assignment, 'type', 'Задание')
                    assign_content = getattr(assignment, 'content', '')
                    assignment_name = f"{assign_type} {assign_content}".strip()

                    assign_type_norm = _normalize_title(assign_type)
                    assignment_name_norm = _normalize_title(assignment_name)
                    if assign_type_norm in self.exclude_titles or assignment_name_norm in self.exclude_titles:
                        continue

                    assignment_key = self._create_assignment_key({
                        'assignmentName': assignment_name,
                        'subjectName': lesson.subject,
                        'date': day.day.strftime('%Y-%m-%d'),
                        'lessonNumber': getattr(lesson, 'number', ''),
                        'lessonStart': getattr(lesson, 'start', ''),
                        'lessonEnd': getattr(lesson, 'end', ''),
                        'comment': getattr(assignment, 'comment', ''),
                        'assignmentIndex': assign_idx
                    })

                    assignment_payload = {
                        'assignmentName': assignment_name,
                        'assignmentType': assign_type,
                        'subjectName': lesson.subject,
                        'date': day.day.strftime('%Y-%m-%d'),
                        'mark': {
                            'value': mark_value
                        },
                        'weight': getattr(assignment, 'weight', None),
                        'assignmentIndex': assign_idx
                    }

                    current_grades[assignment_key] = {
                        "assignment": assignment_payload,
                        "mark": mark_value,
                        "missing_count": 0
                    }

        return current_grades

    async def _confirm_deleted(self, assignment: Dict[str, Any]) -> Optional[bool]:
        """Повторно проверить, удалена ли оценка (True/False), None при ошибке."""
        async def _check_once() -> Optional[bool]:
            try:
                date_str = assignment.get('date', '')
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                week_start = date_obj - timedelta(days=date_obj.weekday())

                diary = await self.ns.diary(start=week_start)
                if not getattr(diary, "schedule", None):
                    return None

                marks_map: Dict[str, bool] = {}
                for day in diary.schedule:
                    for lesson in day.lessons:
                        for ass in lesson.assignments:
                            assign_type = getattr(ass, 'kind', None) or getattr(ass, 'type', 'Задание')
                            assign_content = getattr(ass, 'content', '')
                            assignment_name = f"{assign_type} {assign_content}".strip()

                            key = self._create_assignment_key_loose({
                                'assignmentName': assignment_name,
                                'subjectName': lesson.subject,
                                'date': day.day.strftime('%Y-%m-%d'),
                                'lessonNumber': getattr(lesson, 'number', ''),
                                'lessonStart': getattr(lesson, 'start', ''),
                                'lessonEnd': getattr(lesson, 'end', ''),
                                'comment': getattr(ass, 'comment', '')
                            })

                            mark = ass.mark
                            has_mark = mark is not None
                            marks_map[key] = has_mark

                key = self._create_assignment_key_loose(assignment)
                if key not in marks_map:
                    return True
                return not marks_map[key]
            except Exception:
                return None

        first = await _check_once()
        if first is None:
            return None
        if first is False:
            return False
        await asyncio.sleep(5)
        second = await _check_once()
        if second is None:
            return None
        return first and second
    
    async def send_notification(self, assignment: Dict[str, Any]) -> bool:
        """Отправить уведомление о новой оценке в Telegram"""
        try:
            user_data = self._get_user_data()
            # Получаем информацию об оценке
            assignment_type = assignment.get('assignmentType', assignment.get('assignmentName', 'Задание'))
            date_str = assignment.get('date', '')
            mark_value = assignment.get('mark', {}).get('value', '')
            weight_value = assignment.get('weight')
            
            # Форматируем дату в формат ДД.ММ.ГГГГ
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                formatted_date = date_obj.strftime('%d.%m.%Y')
            except:
                formatted_date = date_str
            
            # Формируем сообщение (БЕЗ оценки, коэффициента и лишнего текста)
            mark_line = f"<b>Оценка:</b> {mark_value}\n" if self.include_mark else ""
            weight_line = (
                f"<b>Вес:</b> {weight_value}\n"
                if weight_value not in (None, "")
                else ""
            )
            message = (
                "🔔 <b>Новая оценка!</b>\n\n"
                f"{self.student_line}"
                f"{mark_line}"
                f"{weight_line}"
                f"<b>Тип:</b> {assignment_type}\n"
                f"<b>Предмет:</b> {assignment.get('subjectName', 'Не указан')}\n"
                f"<b>Дата:</b> {formatted_date}"
            )
            reply_markup = None
            if self.user_id is None:
                feedback_id = _build_grade_feedback_id(assignment)
                store, _ = _ensure_grade_feedback_entry(feedback_id, assignment)
                _save_grade_feedback_store(store)
                reply_markup = _build_grade_feedback_keyboard(feedback_id, store=store)
            telegram_enabled = _should_send_telegram(user_data)
            sent_any = False
            if telegram_enabled:
                await self.bot.send_message(
                    chat_id=self.telegram_chat_id,
                    text=message,
                    parse_mode='HTML',
                    reply_markup=reply_markup,
                    message_thread_id=self.message_thread_id
                )
                sent_any = True
            push_sent = await _send_netschool_web_push(
                self.user_id,
                user_data,
                "NetSchool: новая оценка",
                f"{assignment.get('subjectName', 'Предмет')} · {mark_value} · {formatted_date}",
                "grades",
            )
            sent_any = sent_any or push_sent
            if not sent_any:
                return False
            logger.info(f"Отправлено уведомление о новой оценке: {assignment_type} ({formatted_date})")
            return True
            
        except TelegramRetryAfter as e:
            logger.warning(f"⏳ Flood Control: Необходима пауза {e.retry_after} сек.")
            await asyncio.sleep(e.retry_after + 1)
            # Рекурсивная повторная попытка
            return await self.send_notification(assignment)
            
        except TelegramAPIError as e:
            # Пытаемся извлечь время ожидания из текста ошибки, если это не TelegramRetryAfter
            if "retry after" in str(e).lower():
                import re
                match = re.search(r'retry after (\d+)', str(e).lower())
                if match:
                    wait_time = int(match.group(1))
                    logger.warning(f"⏳ Flood Control (из текста): Необходима пауза {wait_time} сек.")
                    await asyncio.sleep(wait_time + 1)
                    return await self.send_notification(assignment)

            logger.error(f"Ошибка при отправке сообщения в Telegram: {e}")
            return False

    async def send_change_notification(self, assignment: Dict[str, Any], old_mark: Any, new_mark: Any) -> bool:
        """Отправить уведомление об изменении оценки"""
        try:
            user_data = self._get_user_data()
            assignment_type = assignment.get('assignmentType', assignment.get('assignmentName', 'Задание'))
            date_str = assignment.get('date', '')
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                formatted_date = date_obj.strftime('%d.%m.%Y')
            except Exception:
                formatted_date = date_str

            user_line = self.student_line
            message = (
                "⚠️ <b>Изменение оценки</b>\n\n"
                f"{user_line}"
                f"<b>Было:</b> {old_mark}\n"
                f"<b>Стало:</b> {new_mark}\n"
                f"<b>Тип:</b> {assignment_type}\n"
                f"<b>Предмет:</b> {assignment.get('subjectName', 'Не указан')}\n"
                f"<b>Дата:</b> {formatted_date}"
            )

            telegram_enabled = _should_send_telegram(user_data)
            sent_any = False
            if telegram_enabled:
                await self.bot.send_message(
                    chat_id=self.telegram_chat_id,
                    text=message,
                    parse_mode='HTML',
                    message_thread_id=self.message_thread_id
                )
                sent_any = True
            push_sent = await _send_netschool_web_push(
                self.user_id,
                user_data,
                "NetSchool: изменение оценки",
                f"{assignment.get('subjectName', 'Предмет')} · {old_mark} → {new_mark}",
                "grades",
            )
            return sent_any or push_sent
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления об изменении оценки: {e}")
            return False

    async def send_delete_notification(self, assignment: Dict[str, Any]) -> bool:
        """Отправить уведомление об удалении оценки"""
        try:
            user_data = self._get_user_data()
            assignment_type = assignment.get('assignmentType', assignment.get('assignmentName', 'Задание'))
            date_str = assignment.get('date', '')
            old_mark = assignment.get('mark', {}).get('value', '')
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                formatted_date = date_obj.strftime('%d.%m.%Y')
            except Exception:
                formatted_date = date_str

            user_line = self.student_line
            message = (
                "⚠️ <b>Оценка удалена</b>\n\n"
                f"{user_line}"
                f"<b>Оценка:</b> {old_mark}\n"
                f"<b>Тип:</b> {assignment_type}\n"
                f"<b>Предмет:</b> {assignment.get('subjectName', 'Не указан')}\n"
                f"<b>Дата:</b> {formatted_date}"
            )

            telegram_enabled = _should_send_telegram(user_data)
            sent_any = False
            if telegram_enabled:
                await self.bot.send_message(
                    chat_id=self.telegram_chat_id,
                    text=message,
                    parse_mode='HTML',
                    message_thread_id=self.message_thread_id
                )
                sent_any = True
            push_sent = await _send_netschool_web_push(
                self.user_id,
                user_data,
                "NetSchool: оценка удалена",
                f"{assignment.get('subjectName', 'Предмет')} · {old_mark}",
                "grades",
            )
            return sent_any or push_sent
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления об удалении оценки: {e}")
            return False

    async def send_homework_notification(self, homework: Dict[str, Any]) -> bool:
        try:
            user_data = self._get_user_data()
            date_str = homework.get('date', '')
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                formatted_date = date_obj.strftime('%d.%m.%Y')
            except Exception:
                formatted_date = date_str

            attachments = homework.get('attachments') or []
            attachments_line = f"<b>Файлы:</b> {len(attachments)}\n" if attachments else ""
            text_value = str(homework.get('text') or '').strip() or 'Не указана'
            
            # Добавляем текущее время (когда замечено ботом, как ориентир выдачи)
            seen_time = datetime.now().strftime('%d.%m.%Y в %H:%M')

            message = (
                "📝 <b>Новое домашнее задание</b>\n\n"
                f"{self.student_line}"
                f"<b>Предмет:</b> {html.escape(str(homework.get('subjectName', 'Не указан')))}\n"
                f"<b>На урок (сдать):</b> {formatted_date}\n"
                f"<b>Опубликовано/Изменено:</b> ~{seen_time}\n"
                f"<b>Задание:</b> {html.escape(text_value)}\n"
                f"{attachments_line}"
            )

            sent_any = False
            if _should_send_telegram(user_data):
                await self.bot.send_message(
                    chat_id=self.telegram_chat_id,
                    text=message,
                    parse_mode='HTML',
                    message_thread_id=self.message_thread_id,
                )
                sent_any = True
            push_sent = await _send_netschool_web_push(
                self.user_id,
                user_data,
                "NetSchool: новое ДЗ",
                f"{homework.get('subjectName', 'Предмет')} · {formatted_date}",
                "homework",
            )
            sent_any = sent_any or push_sent
            if sent_any:
                logger.info(
                    f"Отправлено уведомление о новом ДЗ: {homework.get('subjectName', '')}, {formatted_date}"
                )
            return sent_any
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления о новом ДЗ: {e}")
            return False
    
    async def check_new_grades(self):
        """Проверить наличие новых оценок (кроме ДЗ и ответов на уроке)"""
        max_retries = 3
        retry_delay = 5  # секунд
        
        for attempt in range(max_retries):
            try:
                if self._session_active:
                    session_alive = await _netschool_session_is_alive(self.ns)
                    if session_alive is False:
                        logger.warning("⚠️ Сессия NetSchool истекла, выполняю повторный вход")
                        await self._reset_netschool_session(clear_saved=True)

                # Если сессия не активна, выполняем вход
                if not self._session_active:
                    if attempt > 0:
                        logger.info(f"Повторная попытка входа NetSchool {attempt + 1}/{max_retries}...")
                    else:
                        logger.info(f"Вход в Сетевой Город...")

                    if self.user_id and await _try_restore_netschool_session(self.user_id, self.ns):
                        session_alive = await _netschool_session_is_alive(self.ns)
                        if session_alive is False:
                            logger.info("⚠️ Сохраненная сессия NetSchool истекла, выполняю обычный вход")
                            await self._reset_netschool_session(clear_saved=True)
                        else:
                            user_data = get_netschool_user(self.user_id)
                            _apply_selected_student_to_client(self.ns, user_data)
                            try:
                                await _sync_user_students_from_ns(self.ns, user_data, persist=True)
                            except Exception:
                                pass
                            self._session_active = True
                            logger.info("✅ Сессия NetSchool восстановлена")
                    else:
                        if self.login_type in ("esia", "esia_qr"):
                            if self.login_type == "esia_qr":
                                # QR-вход нельзя повторить автоматически
                                logger.warning(f"Сессия QR-входа истекла для user {self.user_id}, требуется повторный вход")
                                if self.user_id:
                                    try:
                                        await self.bot.send_message(
                                            self.user_id,
                                            "⚠️ Сессия QR-входа истекла.\n"
                                            "Используйте /relogin для повторного входа.",
                                        )
                                    except Exception:
                                        pass
                                return
                            await self.ns.login_via_gosuslugi(
                                esia_login=self.netschool_login,
                                esia_password=self.netschool_password,
                                school=self.netschool_school or None,
                                timeout=60,
                                otp_callback=_make_esia_mfa_callback(self.user_id, self.bot) if self.user_id else None,
                            )
                        else:
                            await self.ns.login(
                                user_name=self.netschool_login,
                                password=self.netschool_password,
                                school=self.netschool_school
                            )
                        if self.user_id:
                            user_data = get_netschool_user(self.user_id)
                            try:
                                await _sync_user_students_from_ns(self.ns, user_data, persist=True)
                            except Exception:
                                pass
                        self._session_active = True
                        if self.user_id:
                            _save_netschool_session(self.user_id, self.ns)
                            logger.info("✅ Успешный вход в Сетевой Город")

                    if self.user_id:
                        try:
                            fio = await _fetch_student_name(self.ns)
                            if fio:
                                self.user_display_name = fio
                                safe_name = html.escape(fio)
                                self.student_line = f"<b>Ученик:</b> {safe_name}\n"
                                user_data = get_netschool_user(self.user_id)
                                user_data["student_name"] = fio
                                user_data["updated_at"] = datetime.now().isoformat()
                                save_netschool_users()
                        except Exception:
                            pass
                
                # Получаем дневник (используем существующую сессию)
                # ВАЖНО: NetSchool API имеет баг - при запросе большого периода не возвращает все оценки
                # Решение: запрашиваем по неделям и объединяем результаты
                
                # Проверяем 5 недель назад и ограниченное окно вперед.
                today = datetime.now(dt_timezone(timedelta(hours=3))).date()
                five_weeks_ago = today - timedelta(weeks=5)
                five_weeks_ahead = today + timedelta(weeks=2)
                # Приводим старт к понедельнику, чтобы NetSchool гарантированно возвращал нужную неделю
                start_monday = five_weeks_ago - timedelta(days=five_weeks_ago.weekday())
                
                logger.info(
                    f"Проверка оценок за 5 недель назад и 2 недели вперед: "
                    f"с {five_weeks_ago.strftime('%d.%m.%Y')} по {five_weeks_ahead.strftime('%d.%m.%Y')}"
                )
                logger.info("Запрос по неделям для полного охвата...")
                
                # Собираем все дни из всех недель
                all_days = await self._fetch_all_days(start_monday, five_weeks_ahead)

                if self._quiet_hours_active():
                    logger.info(f"🌙 Тихие часы активны для user {self.user_id}, отправка уведомлений отложена")
                    return

                # Проверка почты
                await self._check_mail_updates()

                if self.user_id is not None:
                    user_data = get_netschool_user(self.user_id)
                    last_cache = user_data.get("cache_updated_at")
                    refresh_cache = True
                    try:
                        if last_cache:
                            last_dt = datetime.fromisoformat(last_cache)
                            refresh_cache = (datetime.now() - last_dt) > timedelta(hours=6)
                    except Exception:
                        refresh_cache = True

                    if refresh_cache:
                        cache_start = today - timedelta(weeks=20)
                        cache_end = today + timedelta(weeks=2)
                        cache_start_monday = cache_start - timedelta(days=cache_start.weekday())
                        cache_days = await self._fetch_all_days(cache_start_monday, cache_end)
                        _refresh_user_cache_from_days(self.user_id, cache_days)
                        user_data["cache_updated_at"] = datetime.now().isoformat()
                        user_data["updated_at"] = datetime.now().isoformat()
                        save_netschool_users()
                
                logger.info(f"Получено {len(all_days)} дней с оценками")
                
                # Статистика для логирования
                total_assignments = 0
                excluded_assignments = 0
                already_sent = 0
                new_grades_found = 0
                new_homework_found = 0

                excluded_titles = self.exclude_titles
                
                # Проверяем оценки за каждый день
                current_grades: Dict[str, Dict[str, Any]] = {}
                current_homework: Dict[str, Dict[str, Any]] = {}
                pending_new: list[dict[str, Any]] = []
                pending_events: list[dict[str, Any]] = []
                pending_homework: list[dict[str, Any]] = []
                bulk_prompt_pending = False
                events_prompt_pending = False
                homework_prompt_pending = False
                notify_changes = True
                notify_deletes = True
                notify_homework = False
                if self.user_id is not None:
                    user_data = get_netschool_user(self.user_id)
                    bulk_prompt_pending = bool(user_data.get("bulk_prompt_pending"))
                    events_prompt_pending = bool(user_data.get("events_prompt_pending"))
                    homework_prompt_pending = bool(user_data.get("homework_prompt_pending"))
                    notify_changes = bool(user_data.get("notify_changes", True))
                    notify_deletes = bool(user_data.get("notify_deletes", True))
                    notify_homework = bool(user_data.get("notify_homework", False))
                for day in all_days:
                    for lesson in day.lessons:
                        if not self._subject_allowed(lesson.subject):
                            continue
                        for assign_idx, assignment in enumerate(lesson.assignments):
                            homework_payload = self._build_homework_payload(day, lesson, assignment, assign_idx)
                            if homework_payload is not None:
                                homework_key = self._create_homework_key(homework_payload)
                                current_homework[homework_key] = {
                                    "assignment": homework_payload,
                                    "missing_count": 0,
                                }
                                if self.track_changes and self._known_homework_initialized and homework_key not in self.known_homework:
                                    new_homework_found += 1
                                    logger.info(
                                        f"Найдено новое ДЗ: {homework_payload.get('subjectName', '')}, {homework_payload.get('date', '')}"
                                    )
                                    if notify_homework and not homework_prompt_pending:
                                        pending_homework.append({
                                            "homework": homework_payload,
                                            "key": homework_key,
                                        })

                            # Проверяем, есть ли оценка
                            mark_value = _extract_mark_value(assignment)
                            if assignment.mark is None and mark_value is None:
                                continue
                            
                            total_assignments += 1
                                
                            if mark_value is None or (isinstance(mark_value, str) and mark_value == ""):
                                continue
                            
                            # Получаем тип задания
                            assign_type = getattr(assignment, 'kind', None) or getattr(assignment, 'type', 'Задание')
                            assign_content = getattr(assignment, 'content', '')
                            assignment_name = f"{assign_type} {assign_content}".strip()
                            
                            # ФИЛЬТРАЦИЯ: Исключаем только точные названия
                            assign_type_norm = _normalize_title(assign_type)
                            assignment_name_norm = _normalize_title(assignment_name)

                            if assign_type_norm in excluded_titles or assignment_name_norm in excluded_titles:
                                excluded_assignments += 1
                                continue

                            # Создаём уникальный ID для оценки
                            grade_id = self._create_grade_id({
                                'assignmentName': assignment_name,
                                'subjectName': lesson.subject,
                                'date': day.day.strftime('%Y-%m-%d'),
                                'mark': {
                                    'value': mark_value
                                },
                                'lessonNumber': getattr(lesson, 'number', ''),
                                'lessonStart': getattr(lesson, 'start', ''),
                                'lessonEnd': getattr(lesson, 'end', ''),
                                'comment': getattr(assignment, 'comment', ''),
                                'assignmentIndex': assign_idx
                            })

                            assignment_key = self._create_assignment_key({
                                'assignmentName': assignment_name,
                                'subjectName': lesson.subject,
                                'date': day.day.strftime('%Y-%m-%d'),
                                'lessonNumber': getattr(lesson, 'number', ''),
                                'lessonStart': getattr(lesson, 'start', ''),
                                'lessonEnd': getattr(lesson, 'end', ''),
                                'comment': getattr(assignment, 'comment', ''),
                                'assignmentIndex': assign_idx
                            })

                            assignment_payload = {
                                'assignmentName': assignment_name,
                                'assignmentType': assign_type,
                                'subjectName': lesson.subject,
                                'date': day.day.strftime('%Y-%m-%d'),
                                'mark': {
                                    'value': mark_value
                                },
                                'weight': getattr(assignment, 'weight', None),
                                'assignmentIndex': assign_idx
                            }

                            current_grades[assignment_key] = {
                                "assignment": assignment_payload,
                                "mark": mark_value,
                                "missing_count": 0
                            }
                            
                            # Если оценка новая (не отправляли уведомление)
                            known_mark = None
                            if self.track_changes and assignment_key in self.known_grades:
                                known_mark = self.known_grades.get(assignment_key, {}).get("mark")

                            if self.track_changes and notify_changes and known_mark is not None and str(known_mark) != str(mark_value):
                                new_grades_found += 1
                                logger.info(
                                    f"Изменение оценки: {lesson.subject}, Тип: {assign_type}, Дата: {day.day.strftime('%d.%m.%Y')}, {known_mark} -> {mark_value}"
                                )
                                if not events_prompt_pending:
                                    pending_events.append({
                                        "kind": "change",
                                        "assignment": assignment_payload,
                                        "old_mark": known_mark,
                                        "new_mark": mark_value,
                                        "grade_id": grade_id,
                                    })
                                else:
                                    success = await self.send_change_notification(assignment_payload, known_mark, mark_value)
                                    if success:
                                        self.sent_grades.add(grade_id)
                                        self._save_sent_grades()
                                        await asyncio.sleep(3)
                            elif grade_id not in self.sent_grades:
                                new_grades_found += 1
                                logger.info(f"Найдена новая важная оценка: {lesson.subject}, Тип: {assign_type}, Дата: {day.day.strftime('%d.%m.%Y')}")

                                if self.track_changes and not bulk_prompt_pending:
                                    pending_new.append({
                                        "assignment": assignment_payload,
                                        "grade_id": grade_id
                                    })
                                else:
                                    # Отправляем уведомление
                                    success = await self.send_notification(assignment_payload)

                                    if success:
                                        # Добавляем в список отправленных только если успешно отправили
                                        self.sent_grades.add(grade_id)
                                        self._save_sent_grades()
                                        # Задержка 4 секунды для предотвращения Flood Control
                                        await asyncio.sleep(4)
                                    else:
                                        logger.warning("Не удалось отправить уведомление, попробуем в следующий раз")
                            else:
                                already_sent += 1

                if self.track_changes and not bulk_prompt_pending:
                    if len(pending_new) > 3 and self.user_id is not None:
                        user_data = get_netschool_user(self.user_id)
                        user_data["pending_bulk"] = pending_new
                        user_data["bulk_prompt_pending"] = True
                        user_data["updated_at"] = datetime.now().isoformat()
                        save_netschool_users()

                        await self.bot.send_message(
                            chat_id=self.telegram_chat_id,
                            text=(
                                f"Найдено <b>{len(pending_new)}</b> новых неотправленных оценок.\n"
                                "Показать их одним списком или не отправлять?"
                            ),
                            parse_mode='HTML',
                            reply_markup=_kb_bulk_choice()
                        )
                    elif self.user_id is not None:
                        for item in pending_new:
                            assignment_payload = item.get("assignment", {})
                            grade_id = item.get("grade_id")
                            success = await self.send_notification(assignment_payload)
                            if success and grade_id:
                                self.sent_grades.add(grade_id)
                                self._save_sent_grades()
                                await asyncio.sleep(2)

                if self.track_changes and notify_changes and not events_prompt_pending:
                    if len(pending_events) >= 5 and self.user_id is not None:
                        user_data = get_netschool_user(self.user_id)
                        user_data["pending_events"] = pending_events
                        user_data["events_prompt_pending"] = True
                        user_data["updated_at"] = datetime.now().isoformat()
                        save_netschool_users()

                        await self.bot.send_message(
                            chat_id=self.telegram_chat_id,
                            text=(
                                f"Найдено <b>{len(pending_events)}</b> изменений/удалений.\n"
                                "Отправить их все? Или показать списком одним сообщением?"
                            ),
                            parse_mode='HTML',
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [
                                    InlineKeyboardButton(text="✅ Отправить все", callback_data="ns_events_send_all"),
                                    InlineKeyboardButton(text="📝 Списком", callback_data="ns_events_summary")
                                ],
                                [InlineKeyboardButton(text="❌ Не отправлять", callback_data="ns_events_skip")]
                            ])
                        )
                    elif self.user_id is not None:
                        for item in pending_events:
                            kind = item.get("kind")
                            assignment_payload = item.get("assignment", {})
                            if kind == "change":
                                success = await self.send_change_notification(assignment_payload, item.get("old_mark"), item.get("new_mark"))
                                grade_id = item.get("grade_id")
                                if success and grade_id:
                                    self.sent_grades.add(grade_id)
                                    self._save_sent_grades()
                            elif kind == "delete":
                                await self.send_delete_notification(assignment_payload)
                            await asyncio.sleep(2)

                if self.track_changes:
                    self.known_homework = current_homework
                    self._save_known_homework()

                if self.track_changes and notify_homework and self.user_id is not None:
                    if len(pending_homework) > 3:
                        user_data = get_netschool_user(self.user_id)
                        user_data["pending_homework"] = pending_homework
                        user_data["homework_prompt_pending"] = True
                        user_data["updated_at"] = datetime.now().isoformat()
                        save_netschool_users()
                        await self.bot.send_message(
                            chat_id=self.telegram_chat_id,
                            text=(
                                f"Найдено <b>{len(pending_homework)}</b> новых домашних заданий.\n"
                                "Показать их одним списком или не отправлять?"
                            ),
                            parse_mode='HTML',
                            reply_markup=_kb_homework_choice(),
                        )
                    else:
                        for item in pending_homework[:10]:
                            success = await self.send_homework_notification(item.get("homework", {}))
                            if success:
                                await asyncio.sleep(2)

                if self.track_changes:
                    if current_grades:
                        new_known = dict(self.known_grades or {})
                        for key, payload in current_grades.items():
                            new_known[key] = {
                                "assignment": payload.get("assignment"),
                                "mark": payload.get("mark"),
                                "missing_count": 0
                            }

                        if self._known_grades_initialized:
                            known_count = len(new_known)
                            current_count = len(current_grades)
                            min_expected = max(5, int(known_count * 0.7)) if known_count else 0
                            if known_count and current_count < min_expected:
                                # Повторно получаем данные для точности
                                retry_days = await self._fetch_all_days(start_monday, five_weeks_ahead)
                                retry_map = self._build_current_grades_map(retry_days)
                                retry_count = len(retry_map)
                                if retry_count >= min_expected:
                                    current_grades_for_delete = retry_map
                                    current_count = retry_count
                                else:
                                    logger.warning(
                                        f"⚠️ Слишком мало оценок в ответе ({current_count}/{known_count}), удаление пропущено"
                                    )
                                    current_grades_for_delete = None
                            else:
                                current_grades_for_delete = current_grades
                                # Удаленные оценки (только после повторного отсутствия)
                                removed_keys = [k for k in new_known.keys() if k not in current_grades_for_delete] if current_grades_for_delete is not None else []
                                deleted_count = 0
                                max_delete_per_run = 10
                                recheck_budget = 10
                                for key in removed_keys:
                                    removed = new_known.get(key)
                                    if not removed or not isinstance(removed, dict):
                                        continue
                                    missing_count = int(removed.get("missing_count", 0)) + 1
                                    removed["missing_count"] = missing_count
                                    assignment_payload = removed.get("assignment", {})
                                    # не считаем удалением оценки вне окна проверки (старше 5 недель)
                                    try:
                                        date_str = assignment_payload.get('date', '')
                                        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                                        if date_obj < (datetime.now(dt_timezone(timedelta(hours=3))).date() - timedelta(weeks=5)):
                                            continue
                                    except Exception:
                                        pass
                                    assign_type = assignment_payload.get("assignmentType", "")
                                    assignment_name = assignment_payload.get("assignmentName", "")
                                    assign_type_norm = _normalize_title(assign_type)
                                    assignment_name_norm = _normalize_title(assignment_name)
                                    if assign_type_norm in self.exclude_titles or assignment_name_norm in self.exclude_titles:
                                        continue

                                    if missing_count < 3:
                                        continue
                                    if recheck_budget <= 0:
                                        continue
                                    recheck_budget -= 1
                                    confirmed = await self._confirm_deleted(assignment_payload)
                                    if confirmed is False:
                                        removed["missing_count"] = 0
                                        continue
                                    if confirmed is None:
                                        continue
                                    if deleted_count >= max_delete_per_run:
                                        continue
                                    logger.info(
                                        f"Удаление оценки: {assignment_payload.get('subjectName', '')}, Тип: {assignment_payload.get('assignmentType', '')}, Дата: {assignment_payload.get('date', '')}"
                                    )
                                    if not notify_deletes:
                                        continue
                                    if not events_prompt_pending:
                                        pending_events.append({
                                            "kind": "delete",
                                            "assignment": assignment_payload
                                        })
                                    else:
                                        await self.send_delete_notification(assignment_payload)
                                        await asyncio.sleep(3)
                                    deleted_count += 1
                                    new_known.pop(key, None)

                        self.known_grades = new_known
                        self._save_known_grades()
                        if self.user_id is not None:
                            user_data = get_netschool_user(self.user_id)
                            user_data["last_sync_at"] = now_msk().strftime("%d.%m.%Y %H:%M")
                            user_data["updated_at"] = datetime.now().isoformat()
                            save_netschool_users()
                    else:
                        logger.warning("⚠️ NetSchool вернул пустой список оценок, удаление пропущено")
                
                # Логируем статистику
                logger.info(f"📊 Статистика проверки: Всего оценок: {total_assignments}, "
                           f"Исключено (ДЗ/Ответы): {excluded_assignments}, "
                           f"Уже отправлено: {already_sent}, "
                           f"Новых оценок: {new_grades_found}, "
                           f"Новых ДЗ: {new_homework_found}")
                
                # НЕ выходим из сессии, чтобы сохранить её для следующей проверки
                break
                
            except Exception as e:
                if is_netschool_auth_error(e):
                    logger.warning(f"⚠️ NetSchool вернул ошибку авторизации, сбрасываю сессию: {e}")
                    await self._reset_netschool_session(clear_saved=True)
                    if attempt < max_retries - 1:
                        logger.info(f"Ожидание {retry_delay} секунд перед повторной попыткой входа...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                else:
                    # При любой ошибке считаем сессию недействительной
                    self._session_active = False
                
                error_name = type(e).__name__
                
                # Проверяем, является ли это временной ошибкой сети/сервера
                if is_server_unavailable_error(e) and attempt < max_retries - 1:
                    logger.warning(f"⚠️ Сервер NetSchool не отвечает (попытка {attempt + 1}/{max_retries})")
                    logger.info(f"Ожидание {retry_delay} секунд перед повторной попыткой...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                
                logger.error(f"❌ Ошибка при проверке оценок NetSchool: {error_name}: {e}")
                
                # Отправляем уведомление об ошибке в General (без топика) с cooldown
                import time
                current_time = time.time()

                if not ERROR_NOTIFICATIONS_ENABLED:
                    logger.debug("Уведомления об ошибках подключения NetSchool отключены")
                elif current_time - self._last_error_notification >= self._error_notification_cooldown:
                    try:
                        # Определяем время следующей проверки с учетом ночного режима
                        msk_tz = _msk_tz()
                        now_msk_dt = datetime.now(msk_tz)
                        current_hour = now_msk_dt.hour

                        # С 23:00 до 7:00 по МСК проверяем каждый час, иначе - стандартный интервал
                        if current_hour >= 23 or current_hour < 7:
                            next_check_interval = 3600  # 1 час
                            interval_text = "1 час (ночной режим)"
                        else:
                            next_check_interval = self.check_interval
                            minutes = next_check_interval // 60
                            interval_text = f"{minutes} минут" if minutes > 1 else f"{next_check_interval} секунд"

                        # Определяем куда отправлять (админу в ЛС или в чат)
                        target_bot = self.log_bot if self.log_bot else self.bot
                        target_chat_id = self.admin_id if (self.log_bot and self.admin_id) else self.telegram_chat_id

                        await target_bot.send_message(
                            chat_id=target_chat_id,
                            text=f"⚠️ <b>Ошибка подключения к NetSchool</b>\n\n"
                                 f"Не удалось подключиться к журналу.\n"
                                 f"Ошибка: {error_name}\n"
                                 f"Попыток подключения: {attempt + 1}/{max_retries}\n\n"
                                 f"Попытка повторного подключения через {interval_text}...",
                            parse_mode='HTML'
                        )
                        self._last_error_notification = current_time
                    except Exception as notify_error:
                        logger.error(f"Не удалось отправить уведомление об ошибке: {notify_error}")
                else:
                    time_since_last = int(current_time - self._last_error_notification)
                    logger.debug(f"Уведомление об ошибке пропущено (cooldown: {time_since_last}/{self._error_notification_cooldown} сек)")
                
                break
    
    async def run(self):
        """Запустить мониторинг оценок"""
        try:
            me = await self.bot.get_me()
            logger.info(f"🎓 NetSchool мониторинг запущен (bot=@{me.username}, id={me.id})...")
        except Exception:
            logger.info("🎓 NetSchool мониторинг запущен...")
        logger.info(f"Интервал проверки: {self.check_interval} секунд (днем), 3600 секунд (ночью с 23:00 до 7:00 МСК)")
        
        try:
            while True:
                try:
                    await self.check_new_grades()
                    await self._maybe_send_weekly_summary()
                    
                    # Определяем текущее время по МСК (UTC+3)
                    msk_tz = _msk_tz()
                    now_msk_dt = datetime.now(msk_tz)
                    current_hour = now_msk_dt.hour
                    
                    # С 23:00 до 7:00 по МСК проверяем каждый час, иначе - стандартный интервал
                    if current_hour >= 23 or current_hour < 7:
                        sleep_interval = 3600  # 1 час
                        logger.info(f"🌙 Ночное время ({current_hour:02d}:00 МСК), следующая проверка через 1 час")
                    else:
                        sleep_interval = self.check_interval
                        logger.debug(f"☀️ Дневное время ({current_hour:02d}:00 МСК), следующая проверка через {self.check_interval} секунд")
                    
                    # Закрываем сессию перед ожиданием:
                    try:
                        if self._session_active and hasattr(self.ns, "logout"):
                            await self.ns.logout()
                    except Exception:
                        pass
                    await self._reset_netschool_session(clear_saved=False)
                    
                    await asyncio.sleep(sleep_interval)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Неожиданная ошибка в цикле NetSchool: {e}")
                    await asyncio.sleep(60)
        finally:
            # Закрываем сессии при остановке
            logger.info("Остановка мониторинга NetSchool...")
            if self._session_active:
                try:
                    await _close_netschool_client(self.ns, do_logout=False)
                except:
                    pass
            if self._owns_bot:
                await self.bot.session.close()

