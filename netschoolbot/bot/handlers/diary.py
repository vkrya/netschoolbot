"""Дневник: домашние задания, расписание, звонки, почта, оценки."""

from ._common import *  # noqa: F401,F403
from ._common import *  # noqa: F401,F403


def register(dp: Dispatcher, bot: Bot) -> None:
    @dp.message(Command("dz", "homework"))
    async def ns_cmd_homework(message: Message):
        parts = (message.text or "").split(maxsplit=1)
        custom_date = None
        if len(parts) > 1:
            custom_date = _parse_date_input(parts[1])
            if not custom_date:
                await message.reply("❌ Неверный формат даты. Пример: /dz 25.02 или /dz 25.02.2026")
                return
        else:
            today = datetime.now(dt_timezone(timedelta(hours=3))).date()
            dates = _next_three_days(today)
            keyboard = _build_date_choice_keyboard("dz_date", dates)
            await message.reply("📅 Выберите дату:", reply_markup=keyboard)
            return
        target_dates = {custom_date}
        header = "📚 Домашнее задание (на выбранную дату):"
        await _send_homework_for_dates(message, target_dates, header)

    @dp.callback_query(F.data.startswith("dz_date:"))
    async def ns_dz_date(callback: CallbackQuery):
        raw = (callback.data or "").split(":", 1)[1]
        try:
            selected = datetime.fromisoformat(raw).date()
        except Exception:
            await callback.answer("Неверная дата", show_alert=True)
            return
        await _send_homework_for_dates(
            callback.message,
            {selected},
            "📚 Домашнее задание (на выбранную дату):",
            user_id=callback.from_user.id
        )
        await callback.answer()

    @dp.callback_query(F.data == "dz_files")
    async def ns_dz_files(callback: CallbackQuery):
        user_id = callback.from_user.id
        attachments = runtime.HOMEWORK_ATTACHMENTS_CACHE.get(user_id) or []
        if not attachments:
            await callback.answer("Файлы не найдены", show_alert=True)
            return
        ns = await _get_ns_client(callback.message, user_id=user_id)
        if not ns:
            await callback.answer("Сервис недоступен", show_alert=True)
            return
        await callback.answer()
        status_msg = await callback.message.answer("⌛ Скачиваю файлы...")
        failed = 0
        try:
            for att in attachments:
                filename = att.get("name") or f"file_{att['id']}"
                subject = att.get("subject") or ""
                caption = f"📚 {subject}" if subject else None
                try:
                    buffer = BytesIO()
                    await ns.download_attachment(att["id"], buffer, timeout=90)
                    buffer.seek(0)
                    await callback.message.answer_document(
                        BufferedInputFile(buffer.read(), filename=filename),
                        caption=caption
                    )
                except netschoolpy_exceptions.ServerUnavailable:
                    failed += 1
                    logger.warning(f"ServerUnavailable для вложения {att['id']}")
                except Exception as e:
                    failed += 1
                    logger.warning(f"Ошибка скачивания вложения {att['id']}: {e}")
        finally:
            try:
                await status_msg.delete()
            except Exception:
                pass
            try:
                cached = getattr(ns, "_from_cache", False)
                if not cached:
                    await _close_netschool_client(ns, do_logout=False)
            except Exception:
                pass
        if failed:
            total = len(attachments)
            await callback.message.answer(
                f"⚠️ {failed} из {total} файл(ов) не удалось скачать — сервер не ответил."
            )

    @dp.message(Command("rasp", "schedule"))
    async def ns_cmd_schedule(message: Message):
        parts = (message.text or "").split(maxsplit=1)
        custom_date = None
        if len(parts) > 1:
            custom_date = _parse_date_input(parts[1])
            if not custom_date:
                await message.reply("❌ Неверный формат даты. Пример: /rasp 25.02 или /rasp 25.02.2026")
                return
        else:
            today = datetime.now(dt_timezone(timedelta(hours=3))).date()
            dates = _next_three_days(today)
            keyboard = _build_date_choice_keyboard("rasp_date", dates)
            await message.reply("📅 Выберите дату:", reply_markup=keyboard)
            return
        header = "🗓 Расписание на выбранную дату:"
        await _send_schedule_for_dates(message, {custom_date}, header)

    @dp.callback_query(F.data.startswith("rasp_date:"))
    async def ns_rasp_date(callback: CallbackQuery):
        raw = (callback.data or "").split(":", 1)[1]
        try:
            selected = datetime.fromisoformat(raw).date()
        except Exception:
            await callback.answer("Неверная дата", show_alert=True)
            return
        await _send_schedule_for_dates(
            callback.message,
            {selected},
            "🗓 Расписание на выбранную дату:",
            user_id=callback.from_user.id
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("cal:"))
    async def ns_cal_open(callback: CallbackQuery):
        """cal:<prefix>:<year>:<month> — открыть календарь"""
        parts = (callback.data or "").split(":")
        if len(parts) < 4:
            await callback.answer()
            return
        prefix = parts[1]  # dz_date / rasp_date
        year, month = int(parts[2]), int(parts[3])
        kb = _build_calendar_keyboard(prefix, year, month)
        try:
            await callback.message.edit_text("🗓 Выберите дату:", reply_markup=kb)
        except Exception:
            await callback.message.answer("🗓 Выберите дату:", reply_markup=kb)
        await callback.answer()

    @dp.callback_query(F.data.startswith("cal_nav:"))
    async def ns_cal_nav(callback: CallbackQuery):
        """cal_nav:<prefix>:<year>:<month>:<delta> — переключение месяца"""
        parts = (callback.data or "").split(":")
        if len(parts) < 5:
            await callback.answer()
            return
        prefix = parts[1]
        year, month, delta = int(parts[2]), int(parts[3]), int(parts[4])
        month += delta
        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1
        kb = _build_calendar_keyboard(prefix, year, month)
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass
        await callback.answer()

    @dp.callback_query(F.data == "cal_ignore")
    async def ns_cal_ignore(callback: CallbackQuery):
        await callback.answer()

    @dp.callback_query(F.data == "cal_close")
    async def ns_cal_close(callback: CallbackQuery):
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer()

    @dp.message(Command("bell", "ring"))
    async def ns_cmd_bell(message: Message):
        ns = await _get_ns_client(message)
        if not ns:
            return
        try:
            diary = await ns.diary()
            if not getattr(diary, "schedule", None):
                await message.reply("✅ Расписание отсутствует.")
                return

            today = datetime.now(dt_timezone(timedelta(hours=3))).date()
            day = next((d for d in diary.schedule if d.day == today), None)
            if not day or not day.lessons:
                await message.reply("✅ Сегодня уроков нет.")
                return

            lessons = []
            for lesson in day.lessons:
                if not lesson.start or not lesson.end:
                    continue
                start_dt = datetime.combine(today, lesson.start)
                end_dt = datetime.combine(today, lesson.end)
                lessons.append((start_dt, end_dt, lesson))

            if not lessons:
                await message.reply("✅ Сегодня нет уроков с указанным временем.")
                return

            lessons.sort(key=lambda x: x[0])
            now = datetime.now()
            for start_dt, end_dt, lesson in lessons:
                if now < start_dt:
                    delta = start_dt - now
                    await message.reply(
                        f"⏳ До звонка на урок: {lesson.subject} — {_format_timedelta(delta)}"
                    )
                    return
                if start_dt <= now <= end_dt:
                    delta = end_dt - now
                    await message.reply(
                        f"🔔 До звонка с урока: {lesson.subject} — {_format_timedelta(delta)}"
                    )
                    return

            await message.reply("✅ Уроки на сегодня закончились.")
        finally:
            try:
                cached = getattr(ns, "_from_cache", False)
                if not cached:
                    await _close_netschool_client(ns, do_logout=False)
            except Exception:
                pass

    @dp.message(Command("mail"))
    async def ns_cmd_mail(message: Message):
        await _send_mail_list(message)

    @dp.message(Command("mail_on"))
    async def ns_cmd_mail_on(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["notify_mail"] = True
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await message.answer("✅ Уведомления о почте включены.")

    @dp.message(Command("mail_off"))
    async def ns_cmd_mail_off(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["notify_mail"] = False
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await message.answer("✅ Уведомления о почте отключены.")

    @dp.callback_query(F.data.startswith("mail_read:"))
    async def ns_mail_read(callback: CallbackQuery):
        user_id = callback.from_user.id
        try:
            message_id = int((callback.data or "").split(":", 1)[1])
        except Exception:
            await callback.answer("Неверный ID", show_alert=True)
            return
        ns = await _get_ns_client(callback.message, user_id=user_id)
        if not ns:
            await callback.answer("Сервис недоступен", show_alert=True)
            return
        try:
            mail = await ns.mail_read(message_id)
            sent = mail.sent.strftime("%d.%m.%Y %H:%M")
            subject = mail.subject or "(без темы)"
            author = mail.author_name or "—"
            to_names = mail.to_names or "—"
            body = mail.text or "(пусто)"
            header = (
                f"✉️ {subject}\n"
                f"От: {author}\n"
                f"Кому: {to_names}\n"
                f"Дата: {sent}\n\n"
            )
            full_text = header + body
            for part in _split_message(full_text, max_len=3500):
                await callback.message.answer(part)

            attachments = []
            for att in mail.file_attachments or []:
                attachments.append({"id": att.id, "name": att.name})
            if attachments:
                runtime.MAIL_ATTACHMENTS_CACHE.setdefault(user_id, {})[message_id] = attachments
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📎 Скачать файлы", callback_data=f"mail_files:{message_id}")]
                ])
                await callback.message.answer("Файлы вложены в письмо.", reply_markup=keyboard)
            await callback.answer()
            user_data = get_netschool_user(user_id)
            seen = set(user_data.get("mail_seen_ids") or [])
            seen.add(message_id)
            user_data["mail_seen_ids"] = list(seen)[-200:]
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
        finally:
            try:
                cached = getattr(ns, "_from_cache", False)
                if not cached:
                    await _close_netschool_client(ns, do_logout=False)
            except Exception:
                pass

    @dp.callback_query(F.data.startswith("mail_files:"))
    async def ns_mail_files(callback: CallbackQuery):
        user_id = callback.from_user.id
        try:
            message_id = int((callback.data or "").split(":", 1)[1])
        except Exception:
            await callback.answer("Неверный ID", show_alert=True)
            return
        attachments = runtime.MAIL_ATTACHMENTS_CACHE.get(user_id, {}).get(message_id) or []
        ns = await _get_ns_client(callback.message, user_id=user_id)
        if not ns:
            await callback.answer("Сервис недоступен", show_alert=True)
            return
        try:
            if not attachments:
                mail = await ns.mail_read(message_id)
                attachments = [{"id": a.id, "name": a.name} for a in mail.file_attachments or []]
            if not attachments:
                await callback.answer("Файлы не найдены", show_alert=True)
                return
            await callback.message.answer("⌛ Скачиваю файлы...")
            for att in attachments:
                buffer = BytesIO()
                await ns.download_attachment(att["id"], buffer)
                buffer.seek(0)
                filename = att.get("name") or f"file_{att['id']}"
                await callback.message.answer_document(
                    BufferedInputFile(buffer.read(), filename=filename)
                )
            await callback.answer()
        finally:
            try:
                cached = getattr(ns, "_from_cache", False)
                if not cached:
                    await _close_netschool_client(ns, do_logout=False)
            except Exception:
                pass

    @dp.message(Command("target"))
    async def ns_cmd_target(message: Message):
        parts = message.text.split()
        if len(parts) != 3:
            await message.reply("Использование: /target <оценка> <целевой_балл>\nНапример: /target 5 4.60")
            return
        
        try:
            grade = int(parts[1])
            target_val = float(parts[2].replace(",", "."))
        except ValueError:
            await message.reply("Ошибка: указывайте числа. Пример: /target 5 4.60")
            return
            
        if grade not in [2, 3, 4, 5]:
            await message.reply("Вы можете установить пороги только для оценок 5, 4, 3 или 2.")
            return
            
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id)
        user_data[f"calc_target_{grade}"] = target_val
        save_netschool_users()
        
        await message.reply(f"✅ Порог для оценки «{grade}» успешно изменён на <b>{target_val:.2f}</b>", parse_mode="HTML")

    @dp.message(Command("avg", "average_grade"))
    async def ns_cmd_average(message: Message):
        await message.reply("ℹ️ Средний балл теперь отображается в /grades (выбор предмета) или /grades <предмет>.")

    @dp.message(Command("grades", "all_grades"))
    async def ns_cmd_grades(message: Message):
        parts = message.text.split(maxsplit=1)
        status_text = "⌛ Получаю информацию..." if len(parts) < 2 else "⌛ Получаю оценки..."
        status_msg = await message.answer(status_text)
        ns = await _get_ns_client(message)
        if not ns:
            cache = _load_netschool_cache(message.from_user.id)
            grades_cache = cache.get("grades") or {}
            if len(parts) < 2:
                subjects = grades_cache.get("subjects") or []
                if subjects:
                    runtime.GRADES_SUBJECTS_CACHE[message.from_user.id] = {
                        "subjects": subjects,
                        "ts": datetime.now().isoformat()
                    }
                    keyboard = _build_grades_subjects_keyboard(subjects, page=0)
                    await message.reply("📚 Выберите предмет:", reply_markup=keyboard)
            else:
                subject = parts[1]
                by_subject = grades_cache.get("by_subject") or {}
                cached = by_subject.get(_normalize_subject(subject))
                if cached:
                    await message.reply("⚠️ Сервер недоступен, показываю сохранённые данные.\n\n" + cached)
            try:
                await status_msg.delete()
            except Exception:
                pass
            return
        try:
            user_data = get_netschool_user(message.from_user.id)
            quarter_start = _quarter_start_for_user(user_data)
            today_d = datetime.now(dt_timezone(timedelta(hours=3))).date()
            days_diff = (today_d - quarter_start).days
            weeks_back = max(4, abs(days_diff) // 7 + 2) if days_diff > 0 else 40
            days = await _fetch_diary_days(ns, weeks_back=weeks_back, weeks_forward=2)
            subjects, _ = _collect_grades(days, since_date=quarter_start)
            subjects = sorted(subjects)

            if len(parts) < 2:
                if not subjects:
                    await message.reply("✅ Предметы не найдены.")
                    return
                runtime.GRADES_SUBJECTS_CACHE[message.from_user.id] = {
                    "subjects": subjects,
                    "ts": datetime.now().isoformat()
                }
                keyboard = _build_grades_subjects_keyboard(subjects, page=0)
                await message.reply(
                    "📚 Выберите предмет:",
                    reply_markup=keyboard
                )
                cache = _load_netschool_cache(message.from_user.id)
                cache["grades"] = {
                    **(cache.get("grades") or {}),
                    "subjects": subjects,
                    "updated_at": datetime.now().isoformat()
                }
                _save_netschool_cache(message.from_user.id, cache)
                return

            await _send_grades_for_subject(message, parts[1], days)
        finally:
            try:
                cached = getattr(ns, "_from_cache", False)
                if not cached:
                    await _close_netschool_client(ns, do_logout=False)
            except Exception:
                pass
            try:
                await status_msg.delete()
            except Exception:
                pass

    @dp.callback_query(F.data.startswith("grades_page:"))

    async def ns_grades_page(callback: CallbackQuery):
        user_id = callback.from_user.id
        cache = runtime.GRADES_SUBJECTS_CACHE.get(user_id)
        if not cache or not cache.get("subjects"):
            await callback.answer("Список устарел. Отправьте /grades", show_alert=True)
            return
        try:
            page = int((callback.data or "").split(":", 1)[1])
        except Exception:
            await callback.answer()
            return
        page = max(0, page)
        keyboard = _build_grades_subjects_keyboard(cache["subjects"], page=page)
        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer()

    @dp.callback_query(F.data.startswith("grades_subj:"))
    async def ns_grades_subject(callback: CallbackQuery):
        user_id = callback.from_user.id
        cache = runtime.GRADES_SUBJECTS_CACHE.get(user_id)
        if not cache or not cache.get("subjects"):
            await callback.answer("Список устарел. Отправьте /grades", show_alert=True)
            return
        try:
            idx = int((callback.data or "").split(":", 1)[1])
        except Exception:
            await callback.answer()
            return
        subjects = cache["subjects"]
        if idx < 0 or idx >= len(subjects):
            await callback.answer("Предмет не найден", show_alert=True)
            return
        subject = subjects[idx]
        status_msg = await callback.message.answer("⌛ Получаю оценки...")
        ns = await _get_ns_client(callback.message, user_id=user_id)
        if not ns:
            cached = _load_netschool_cache(user_id).get("grades", {}).get("by_subject", {}).get(_normalize_subject(subject))
            if cached:
                await callback.message.answer("⚠️ Сервер недоступен, показываю сохранённые данные.\n\n" + cached)
            await callback.answer()
            try:
                await status_msg.delete()
            except Exception:
                pass
            return
        try:
            user_data = get_netschool_user(user_id)
            quarter_start = _quarter_start_for_user(user_data)
            today_d = datetime.now(dt_timezone(timedelta(hours=3))).date()
            days_diff = (today_d - quarter_start).days
            weeks_back = max(4, abs(days_diff) // 7 + 2) if days_diff > 0 else 40
            days = await _fetch_diary_days(ns, weeks_back=weeks_back, weeks_forward=2)
            await _send_grades_for_subject(callback.message, subject, days, exact_subject=True, q_start=quarter_start)
            await callback.answer()
        finally:
            try:
                cached = getattr(ns, "_from_cache", False)
                if not cached:
                    await _close_netschool_client(ns, do_logout=False)
            except Exception:
                pass
            try:
                await status_msg.delete()
            except Exception:
                pass

