"""Настройки уведомлений: интервал, фильтры, тихие часы, сводка."""

from ._common import *  # noqa: F401,F403
from ._common import *  # noqa: F401,F403


def register(dp: Dispatcher, bot: Bot) -> None:
    @dp.callback_query(F.data.startswith("ns_qh:"))
    async def ns_quiet_hours_preset(callback: CallbackQuery):
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id, callback.from_user.full_name)
        payload = (callback.data or "").split(":", 1)[1]
        if payload == "off":
            user_data["quiet_hours"] = {"start": "", "end": ""}
            text = "✅ Тихие часы отключены."
        else:
            try:
                start, end = payload.split("|", 1)
                if not start or not end:
                    raise ValueError
            except Exception:
                await callback.answer("Неверный диапазон", show_alert=True)
                return
            user_data["quiet_hours"] = {"start": start, "end": end}
            text = f"✅ Тихие часы: {start} - {end}"
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await callback.message.answer(text, reply_markup=_build_netschool_main_menu(user_data))
        await callback.answer()

    @dp.callback_query(F.data.startswith("ns_sf_page:"))
    async def ns_subject_filter_page(callback: CallbackQuery):
        user_id = callback.from_user.id
        cache = runtime.GRADES_SUBJECTS_CACHE.get(user_id)
        if not cache or not cache.get("subjects"):
            await callback.answer("Список устарел. Откройте «Предметы» ещё раз.", show_alert=True)
            return
        try:
            page = int((callback.data or "").split(":", 1)[1])
        except Exception:
            await callback.answer()
            return
        selected = get_user_subject_include_titles(get_netschool_user(user_id, callback.from_user.full_name))
        await callback.message.edit_reply_markup(
            reply_markup=_build_subject_filter_keyboard(cache["subjects"], selected, page=max(0, page))
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("ns_sf_toggle:"))
    async def ns_subject_filter_toggle(callback: CallbackQuery):
        user_id = callback.from_user.id
        cache = runtime.GRADES_SUBJECTS_CACHE.get(user_id)
        if not cache or not cache.get("subjects"):
            await callback.answer("Список устарел. Откройте «Предметы» ещё раз.", show_alert=True)
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
        user_data = get_netschool_user(user_id, callback.from_user.full_name)
        selected_raw = user_data.setdefault("subject_filters", {}).setdefault("include", [])
        subject = subjects[idx]
        if subject in selected_raw:
            selected_raw.remove(subject)
            message = f"Убрано: {subject}"
        else:
            selected_raw.append(subject)
            message = f"Добавлено: {subject}"
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
        selected = get_user_subject_include_titles(user_data)
        await callback.message.edit_reply_markup(
            reply_markup=_build_subject_filter_keyboard(subjects, selected, page=idx // 8)
        )
        await callback.answer(message)

    @dp.callback_query(F.data == "ns_sf_reset")
    async def ns_subject_filter_reset(callback: CallbackQuery):
        user_id = callback.from_user.id
        cache = runtime.GRADES_SUBJECTS_CACHE.get(user_id)
        if not cache or not cache.get("subjects"):
            await callback.answer("Список устарел. Откройте «Предметы» ещё раз.", show_alert=True)
            return
        user_data = get_netschool_user(user_id, callback.from_user.full_name)
        user_data.setdefault("subject_filters", {})["include"] = []
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
        await callback.message.edit_reply_markup(
            reply_markup=_build_subject_filter_keyboard(cache["subjects"], set(), page=0)
        )
        await callback.answer("Фильтр предметов сброшен")

    @dp.message(Command("settings"))
    async def ns_cmd_settings(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        await message.answer(
            _build_settings_text(user_data),
            parse_mode="HTML",
            reply_markup=_build_settings_keyboard(user_data)
        )

    @dp.callback_query(F.data.startswith("ns_toggle:"))
    async def ns_toggle_setting(callback: CallbackQuery):
        if callback.message.chat.type != "private":
            await callback.answer()
            return
        user_id = callback.from_user.id
        key = (callback.data or "").split(":", 1)[1]
        user_data = get_netschool_user(user_id, callback.from_user.full_name)

        if key == "enabled":
            new_val = not bool(user_data.get("enabled"))
            user_data["enabled"] = new_val
            if new_val:
                asyncio.create_task(
                    refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID),
                    name=f"ns_toggle_on_{user_id}"
                )
            else:
                asyncio.create_task(
                    stop_user_grade_task(user_id),
                    name=f"ns_toggle_off_{user_id}"
                )
        elif key == "changes":
            user_data["notify_changes"] = not bool(user_data.get("notify_changes", True))
        elif key == "deletes":
            user_data["notify_deletes"] = not bool(user_data.get("notify_deletes", True))
        elif key == "mail":
            user_data["notify_mail"] = not bool(user_data.get("notify_mail", True))
        elif key == "weekly":
            user_data["weekly_summary_enabled"] = not bool(user_data.get("weekly_summary_enabled"))
        else:
            await callback.answer("Неизвестная настройка", show_alert=True)
            return

        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()

        try:
            await callback.message.edit_text(
                _build_settings_text(user_data),
                parse_mode="HTML",
                reply_markup=_build_settings_keyboard(user_data)
            )
        except Exception:
            pass
        await callback.answer()

    @dp.message(Command("changes_on"))
    async def ns_cmd_changes_on(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["notify_changes"] = True
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await message.answer("✅ Уведомления об изменении оценок включены.")

    @dp.message(Command("changes_off"))
    async def ns_cmd_changes_off(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["notify_changes"] = False
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await message.answer("🔕 Уведомления об изменении оценок отключены.")

    @dp.message(Command("deletes_on"))
    async def ns_cmd_deletes_on(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["notify_deletes"] = True
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await message.answer("✅ Уведомления об удалении оценок включены.")

    @dp.message(Command("deletes_off"))
    async def ns_cmd_deletes_off(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["notify_deletes"] = False
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await message.answer("🔕 Уведомления об удалении оценок отключены.")

    @dp.message(Command("hw_on"))
    async def ns_cmd_hw_on(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["notify_homework"] = True
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await message.answer("✅ Уведомления о новых ДЗ включены.")

    @dp.message(Command("hw_off"))
    async def ns_cmd_hw_off(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["notify_homework"] = False
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await message.answer("🔕 Уведомления о новых ДЗ отключены.")

    @dp.message(Command("on"))
    async def ns_cmd_on(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["enabled"] = True
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
        await message.answer("✅ Уведомления включены.")

    @dp.message(Command("off"))
    async def ns_cmd_off(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["enabled"] = False
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await stop_user_grade_task(user_id)
        await message.answer("🔕 Уведомления выключены.")

    @dp.message(Command("interval"))
    async def ns_cmd_interval(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        current_interval = user_data.get("check_interval", 600)
        
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                f"⏱ Текущий интервал проверки: {current_interval // 60} мин.\n\n"
                f"Чтобы изменить, используйте:\n"
                f"• /interval 10м (10 минут)\n"
                f"• /interval 5m (5 минут)\n"
                f"• /interval 1ч (1 час)\n"
                f"• /interval 600 (600 секунд)",
                reply_markup=_build_interval_presets_keyboard()
            )
            return
        seconds = parse_interval_input(parts[1])
        if seconds is None:
            await message.answer("❌ Неверный формат интервала. Пример: 10м, 5m, 1ч, или 600")
            return
        seconds = _clamp_interval(seconds)
        user_data["check_interval"] = seconds
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
        await message.answer(f"✅ Интервал проверки установлен: {seconds // 60} мин.")

    @dp.callback_query(F.data.startswith("ns_interval:"))
    async def ns_interval_preset(callback: CallbackQuery):
        user_id = callback.from_user.id
        try:
            seconds = int((callback.data or "").split(":", 1)[1])
        except Exception:
            await callback.answer("Неверный интервал", show_alert=True)
            return
        seconds = _clamp_interval(seconds)
        user_data = get_netschool_user(user_id, callback.from_user.full_name)
        user_data["check_interval"] = seconds
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
        await callback.message.answer(f"✅ Интервал проверки установлен: {seconds // 60} мин.")
        await callback.answer()

    @dp.message(Command("filter"))
    async def ns_cmd_filter(message: Message):
        if message.chat.type != "private":
            return
        parts = message.text.split(maxsplit=2)
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        filters = user_data.setdefault("filters", {"exclude": _default_exclude_titles()})
        exclude_list = filters.setdefault("exclude", _default_exclude_titles())

        if len(parts) == 1 or parts[1].lower() == "list":
            current = ", ".join(exclude_list) or "нет"
            await message.answer(
                "🧰 <b>Фильтр типов</b>\n\n"
                f"Исключенные типы: {current}\n\n"
                "Команды:\n"
                "• /filter add Контрольная\n"
                "• /filter remove Домашнее задание\n"
                "• /filter reset",
                parse_mode="HTML"
            )
            return

        action = parts[1].lower()
        if action == "reset":
            filters["exclude"] = _default_exclude_titles()
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
            await message.answer("✅ Фильтр сброшен к значениям по умолчанию.")
            return

        if len(parts) < 3:
            await message.answer("Укажите тип: /filter add Контрольная")
            return

        value = parts[2].strip()
        if not value:
            await message.answer("❌ Пустое значение фильтра.")
            return

        if action == "add":
            if value not in exclude_list:
                exclude_list.append(value)
                user_data["updated_at"] = datetime.now().isoformat()
                save_netschool_users()
                await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
            await message.answer(f"✅ Исключен тип: {value}")
            return

        if action == "remove":
            if value in exclude_list:
                exclude_list.remove(value)
                user_data["updated_at"] = datetime.now().isoformat()
                save_netschool_users()
                await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
            await message.answer(f"✅ Тип разрешен: {value}")
            return

        await message.answer("❌ Неизвестное действие. Используйте add/remove/reset/list.")

    @dp.message(Command("subjectfilter"))
    async def ns_cmd_subjectfilter(message: Message):
        if message.chat.type != "private":
            return
        parts = (message.text or "").split(maxsplit=2)
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        subject_filters = user_data.setdefault("subject_filters", {"include": []})
        include_list = subject_filters.setdefault("include", [])

        if len(parts) == 1 or parts[1].lower() == "list":
            current = ", ".join(include_list) or "все предметы"
            await message.answer(
                "📚 <b>Фильтр предметов</b>\n\n"
                f"Сейчас приходят уведомления по: {current}\n\n"
                "Команды:\n"
                "• /subjectfilter add Алгебра\n"
                "• /subjectfilter remove Алгебра\n"
                "• /subjectfilter reset",
                parse_mode="HTML"
            )
            return

        action = parts[1].lower()
        if action == "reset":
            subject_filters["include"] = []
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
            await message.answer("✅ Фильтр предметов сброшен. Теперь приходят все предметы.")
            return

        if len(parts) < 3 or not parts[2].strip():
            await message.answer("Укажите предмет: /subjectfilter add Алгебра")
            return

        value = parts[2].strip()
        if action == "add":
            if value not in include_list:
                include_list.append(value)
                user_data["updated_at"] = datetime.now().isoformat()
                save_netschool_users()
                await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
            await message.answer(f"✅ Добавлен предмет: {value}")
            return
        if action == "remove":
            if value in include_list:
                include_list.remove(value)
                user_data["updated_at"] = datetime.now().isoformat()
                save_netschool_users()
                await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
            await message.answer(f"✅ Предмет убран из фильтра: {value}")
            return

        await message.answer("❌ Неизвестное действие. Используйте add/remove/reset/list.")

    @dp.message(Command("quiethours", "quiet"))
    async def ns_cmd_quiet_hours(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        parts = (message.text or "").split()
        if len(parts) == 1:
            await message.answer(
                "🌙 <b>Тихие часы</b>\n\n"
                f"Сейчас: {format_user_quiet_hours(user_data)}\n\n"
                "Примеры:\n"
                "• /quiethours 23:00 07:00\n"
                "• /quiethours off",
                parse_mode="HTML"
            )
            return
        if len(parts) == 2 and parts[1].lower() in {"off", "disable", "reset"}:
            user_data["quiet_hours"] = {"start": "", "end": ""}
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            await message.answer("✅ Тихие часы отключены.")
            return
        if len(parts) < 3:
            await message.answer("❌ Укажите диапазон: /quiethours 23:00 07:00")
            return
        start = _parse_hhmm(parts[1])
        end = _parse_hhmm(parts[2])
        if not start or not end:
            await message.answer("❌ Неверный формат времени. Используйте HH:MM, например 23:00 07:00")
            return
        user_data["quiet_hours"] = {"start": start, "end": end}
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await message.answer(f"✅ Тихие часы установлены: {start} - {end}")

    @dp.message(Command("weekly_on"))
    async def ns_cmd_weekly_on(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["weekly_summary_enabled"] = True
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await message.answer("✅ Автоматическая недельная сводка включена. Она будет приходить по понедельникам утром.")

    @dp.message(Command("weekly_off"))
    async def ns_cmd_weekly_off(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["weekly_summary_enabled"] = False
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await message.answer("🔕 Автоматическая недельная сводка отключена.")

