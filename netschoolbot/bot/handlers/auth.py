"""Вход в «Сетевой город»: регион, школа, пароль/Госуслуги/QR и диалоговый флоу."""

from ._common import *  # noqa: F401,F403
from ._common import *  # noqa: F401,F403


def register(dp: Dispatcher, bot: Bot) -> None:
    @dp.message(Command("login"))
    async def ns_cmd_login(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        if user_data.get("login") and user_data.get("password") and user_data.get("enabled"):
            await message.answer("Вы уже вошли. Используйте /relogin для повторного входа или /logout для выхода.")
            return
        user_data["login"] = ""
        user_data["password"] = ""
        user_data["enabled"] = False
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await stop_user_grade_task(user_id)
        await stop_login_retry_task(user_id)
        # Проверяем ЛИЧНЫЕ настройки пользователя (без фолбека на глобальные)
        own_url = user_data.get("netschool_url") or ""
        own_school = str(user_data.get("netschool_school") or "")
        if own_url and own_school:
            await _proceed_to_auth(message, user_id, user_data, own_url, own_school)
        else:
            # Нет личных настроек — начинаем с выбора региона
            set_netschool_user_state(user_id, "await_region")
            await message.answer(
                "🔐 Давайте подключим журнал.\n"
                "Выберите ваш регион:",
                reply_markup=_build_region_keyboard()
            )

    @dp.message(Command("logout"))
    async def ns_cmd_logout(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["login"] = ""
        user_data["password"] = ""
        user_data["enabled"] = False
        user_data["bulk_prompt_pending"] = False
        user_data["pending_bulk"] = []
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await stop_user_grade_task(user_id)
        await stop_login_retry_task(user_id)
        await _close_netschool_session(user_id)
        set_netschool_user_state(user_id, None)
        await message.answer("✅ Вы вышли из журнала. Для повторного входа используйте /login.")

    @dp.message(Command("relogin"))
    async def ns_cmd_relogin(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        user_data["login"] = ""
        user_data["password"] = ""
        user_data["enabled"] = False
        user_data["bulk_prompt_pending"] = False
        user_data["pending_bulk"] = []
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await stop_user_grade_task(user_id)
        await stop_login_retry_task(user_id)
        await _close_netschool_session(user_id)
        # Если у пользователя была школа — предложить войти в неё или сменить
        own_url = user_data.get("netschool_url") or ""
        own_school = user_data.get("netschool_school") or ""
        if own_url and own_school:
            set_netschool_user_state(user_id, "await_relogin_choice")
            await message.answer(
                f"🔐 Повторный вход.\n"
                f"Последняя школа: <b>{html.escape(own_school)}</b>\n\n"
                "Войти в неё или сменить?",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"🏫 Войти в {own_school[:30]}", callback_data="ns_relogin_keep")],
                    [InlineKeyboardButton(text="🌍 Сменить регион/школу", callback_data="ns_choose_region")],
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="ns_back_cancel")],
                ])
            )
        else:
            set_netschool_user_state(user_id, "await_region")
            await message.answer(
                "🔐 Давайте войдем заново.\n"
                "Выберите регион:",
                reply_markup=_build_region_keyboard()
            )

    @dp.callback_query(F.data == "ns_back_cancel")
    async def ns_back_cancel(callback: CallbackQuery):
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id)
        state = _get_netschool_user_state(user_id)

        # Отменяем любой ожидающий OTP-фьючерс
        future = esia_otp_futures.pop(user_id, None)
        if future and not future.done():
            future.cancel()

        if state == "await_esia_otp":
            # Возврат к повторному вводу пароля ЕСИА
            set_netschool_user_state(user_id, "await_esia_password")
            await callback.message.answer(
                "🔒 Отправьте пароль от Госуслуг повторно.",
                reply_markup=_kb_back_cancel()
            )
        elif state == "await_esia_password":
            # Возврат к вводу логина ЕСИА
            set_netschool_user_state(user_id, "await_esia_login")
            await callback.message.answer(
                "🏛 Отправьте логин Госуслуг (телефон, email или СНИЛС).",
                reply_markup=_kb_back_cancel()
            )
        elif state in ("await_esia_login", "await_login"):
            # Возврат к выбору метода входа (если есть URL и школа)
            user_url = _get_user_ns_url(user_data)
            user_school = _get_user_ns_school(user_data)
            if user_url and user_school:
                await _proceed_to_auth(callback.message, user_id, user_data, user_url, user_school)
            else:
                set_netschool_user_state(user_id, None)
                await callback.message.answer(
                    "Ок, возвращаю в главное меню.",
                    reply_markup=_build_netschool_main_menu(user_data)
                )
        elif state == "await_auth_method":
            # Возврат к поиску школы
            set_netschool_user_state(user_id, "await_school_search")
            await callback.message.answer(
                "🏫 Введите часть названия школы для поиска:",
                reply_markup=_kb_back_cancel()
            )
        elif state in ("await_school_search", "await_custom_url", "await_select_school"):
            # Возврат к выбору региона
            set_netschool_user_state(user_id, "await_region")
            await callback.message.answer(
                "🌍 Выберите регион:",
                reply_markup=_build_region_keyboard()
            )
        elif state == "await_password":
            # Возврат к вводу логина журнала
            set_netschool_user_state(user_id, "await_login")
            await callback.message.answer(
                "🔐 Отправьте логин от журнала одним сообщением.",
                reply_markup=_kb_back_cancel()
            )
        elif state == "await_bugreport":
            set_netschool_user_state(user_id, None)
            await callback.message.answer(
                "Ок, отправка баг-репорта отменена.",
                reply_markup=_build_netschool_main_menu(user_data)
            )
        elif state and state.startswith("await_calc_target_"):
            set_netschool_user_state(user_id, None)
            await callback.message.answer(
                "Ок, изменение порога отменено.",
                reply_markup=_build_netschool_main_menu(user_data)
            )
        else:
            # Самый верхний уровень — отменяем
            set_netschool_user_state(user_id, None)
            await callback.message.answer(
                "Ок, возвращаю в главное меню.",
                reply_markup=_build_netschool_main_menu(user_data)
            )
        await callback.answer()

    @dp.message(Command("cancel"))
    async def ns_cmd_cancel(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        future = esia_otp_futures.pop(user_id, None)
        if future and not future.done():
            future.cancel()
        set_netschool_user_state(user_id, None)
        await message.answer(
            "Ок, действие отменено.",
            reply_markup=_build_netschool_main_menu(get_netschool_user(user_id, message.from_user.full_name))
        )

    @dp.callback_query(F.data == "ns_back_login")
    async def ns_back_login(callback: CallbackQuery):
        user_id = callback.from_user.id
        set_netschool_user_state(user_id, "await_login")
        await callback.message.answer("Отправьте логин от журнала одним сообщением.", reply_markup=_kb_back_cancel())
        await callback.answer()

    @dp.callback_query(F.data == "ns_choose_region")
    async def ns_choose_region(callback: CallbackQuery):
        user_id = callback.from_user.id
        set_netschool_user_state(user_id, "await_region")
        await callback.message.answer("🌍 Выберите регион:", reply_markup=_build_region_keyboard())
        await callback.answer()

    @dp.callback_query(F.data.startswith("ns_region:"))
    async def ns_region_chosen(callback: CallbackQuery):
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id)
        raw = (callback.data or "").split(":", 1)[1]
        if raw == "custom_url":
            set_netschool_user_state(user_id, "await_custom_url")
            await callback.message.answer(
                "🌐 Введите URL вашего Сетевого города (SGO).\n"
                "Пример: https://sgo.edu-74.ru",
                reply_markup=_kb_back_cancel()
            )
            await callback.answer()
            return
        # raw = индекс региона
        from netschoolpy import list_regions, REGIONS
        regions = list_regions()
        try:
            idx = int(raw)
            region_name = regions[idx]
        except (ValueError, IndexError):
            await callback.answer("Регион не найден", show_alert=True)
            return
        url = REGIONS.get(region_name)
        if not url:
            await callback.answer("Регион не найден", show_alert=True)
            return
        user_data["netschool_url"] = url
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        set_netschool_user_state(user_id, "await_school_search")
        await callback.message.answer(
            f"✅ Регион: {region_name}\n\n"
            "🏫 Введите часть названия школы для поиска:\n"
            "Пример: Лицей или Школа №1",
            reply_markup=_kb_back_cancel()
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("ns_region_page:"))
    async def ns_region_page(callback: CallbackQuery):
        page = int((callback.data or "").split(":", 1)[1])
        try:
            await callback.message.edit_reply_markup(reply_markup=_build_region_keyboard(page))
        except Exception:
            pass
        await callback.answer()

    @dp.callback_query(F.data.startswith("ns_school:"))
    async def ns_school_chosen(callback: CallbackQuery):
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id)
        raw = (callback.data or "").split(":", 1)[1]
        try:
            idx = int(raw)
            cached = runtime._SCHOOL_SEARCH_CACHE.get(user_id, [])
            school_name = cached[idx] if idx < len(cached) else raw
        except (ValueError, IndexError):
            school_name = raw
        user_data["netschool_school"] = school_name
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()

        # Определяем доступные способы входа
        user_url = _get_user_ns_url(user_data)
        loading_msg = await callback.message.answer("⏳ Определяю доступные способы входа...")
        login_methods = None
        try:
            from netschoolpy import get_login_methods
            login_methods = await get_login_methods(user_url, timeout=10)
        except Exception as e:
            logger.warning(f"Не удалось получить способы входа для {user_url}: {e}")
        try:
            await loading_msg.delete()
        except Exception:
            pass

        if login_methods and login_methods.esia_main and not login_methods.password:
            # Только Госуслуги — выбор: логин/пароль или QR
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏛 Госуслуги (логин/пароль)", callback_data="ns_auth_method:esia")],
                [InlineKeyboardButton(text="📱 Госуслуги (QR-код)", callback_data="ns_auth_method:esia_qr")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")],
            ])
            set_netschool_user_state(user_id, "await_auth_method")
            await callback.message.answer(
                f"✅ Школа: {school_name}\n"
                f"🔑 Вход только через Госуслуги\n\n"
                "Выберите способ:",
                reply_markup=kb
            )
        elif login_methods and login_methods.esia and login_methods.password:
            # Оба способа — предлагаем выбор
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Логин и пароль журнала", callback_data="ns_auth_method:password")],
                [InlineKeyboardButton(text="🏛 Госуслуги (логин/пароль)", callback_data="ns_auth_method:esia")],
                [InlineKeyboardButton(text="📱 Госуслуги (QR-код)", callback_data="ns_auth_method:esia_qr")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")],
            ])
            set_netschool_user_state(user_id, "await_auth_method")
            await callback.message.answer(
                f"✅ Школа: {school_name}\n\n"
                "Выберите способ входа:",
                reply_markup=kb
            )
        else:
            # Только логин/пароль (или не удалось определить)
            user_data["login_type"] = "password"
            save_netschool_users()
            set_netschool_user_state(user_id, "await_login")
            await callback.message.answer(
                f"✅ Школа: {school_name}\n\n"
                "🔐 Отправьте логин от журнала одним сообщением.",
                reply_markup=_kb_back_cancel()
            )
        await callback.answer()

    @dp.callback_query(F.data == "ns_school_retry")
    async def ns_school_retry(callback: CallbackQuery):
        set_netschool_user_state(callback.from_user.id, "await_school_search")
        await callback.message.answer(
            "🏫 Введите часть названия школы для поиска:",
            reply_markup=_kb_back_cancel()
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("ns_auth_method:"))
    async def ns_auth_method_chosen(callback: CallbackQuery):
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id)
        method = (callback.data or "").split(":", 1)[1]
        user_data["login_type"] = method
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        if method == "esia":
            set_netschool_user_state(user_id, "await_esia_login")
            await callback.message.answer(
                "🏛 Вход через Госуслуги.\n\n"
                "Отправьте логин Госуслуг (телефон, email или СНИЛС).",
                reply_markup=_kb_back_cancel()
            )
        elif method == "esia_qr":
            await callback.answer()
            await _start_qr_login(callback.message, user_id, user_data)
            return
        else:
            set_netschool_user_state(user_id, "await_login")
            await callback.message.answer(
                "🔐 Отправьте логин от журнала одним сообщением.",
                reply_markup=_kb_back_cancel()
            )
        await callback.answer()

    @dp.callback_query(F.data == "ns_relogin_keep")
    async def ns_relogin_keep(callback: CallbackQuery):
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id)
        own_url = user_data.get("netschool_url") or ""
        own_school = user_data.get("netschool_school") or ""
        if not own_url or not own_school:
            await callback.answer("Школа не найдена", show_alert=True)
            return
        await callback.answer()
        await _proceed_to_auth(callback.message, user_id, user_data, own_url, own_school)

    @dp.callback_query(F.data == "ns_qr_retry")
    async def ns_qr_retry(callback: CallbackQuery):
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id)
        await callback.answer()
        await _start_qr_login(callback.message, user_id, user_data)

    @dp.callback_query(F.data.in_({"ns_bulk_send_all", "ns_bulk_summary", "ns_bulk_skip"}))
    async def ns_bulk_decision(callback: CallbackQuery):
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id)
        items = user_data.get("pending_bulk") or []
        if not items:
            await callback.message.answer("ℹ️ Нет ожидающих оценок.")
            await callback.answer()
            return

        decision = callback.data
        notifier = runtime.netschool_user_notifiers.get(user_id)

        if decision in {"ns_bulk_send_all", "ns_bulk_summary"}:
            summary = _format_bulk_summary(items)
            await callback.message.answer(
                "📝 <b>Список новых оценок</b>\n\n" + summary,
                parse_mode="HTML"
            )
            if notifier:
                for item in items:
                    grade_id = item.get("grade_id")
                    if grade_id:
                        notifier.sent_grades.add(grade_id)
                notifier._save_sent_grades()

        else:
            await callback.message.answer("❌ Оценки не отправлены.")
            if notifier:
                for item in items:
                    grade_id = item.get("grade_id")
                    if grade_id:
                        notifier.sent_grades.add(grade_id)
                notifier._save_sent_grades()

        user_data["pending_bulk"] = []
        user_data["bulk_prompt_pending"] = False
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await callback.answer()

    @dp.callback_query(F.data.in_({"ns_events_send_all", "ns_events_summary", "ns_events_skip"}))
    async def ns_events_decision(callback: CallbackQuery):
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id)
        items = user_data.get("pending_events") or []
        if not items:
            await callback.message.answer("ℹ️ Нет ожидающих уведомлений.")
            await callback.answer()
            return

        decision = callback.data
        notifier = runtime.netschool_user_notifiers.get(user_id)

        if decision == "ns_events_send_all" and notifier:
            for item in items:
                kind = item.get("kind")
                assignment = item.get("assignment", {})
                if kind == "change":
                    success = await notifier.send_change_notification(assignment, item.get("old_mark"), item.get("new_mark"))
                    grade_id = item.get("grade_id")
                    if success and grade_id:
                        notifier.sent_grades.add(grade_id)
                elif kind == "delete":
                    await notifier.send_delete_notification(assignment)
                await asyncio.sleep(1)
            notifier._save_sent_grades()
            await callback.message.answer("✅ Уведомления отправлены.")
        elif decision == "ns_events_summary":
            summary = _format_events_summary(items)
            await callback.message.answer(
                "📝 <b>Список изменений</b>\n\n" + summary,
                parse_mode="HTML"
            )
            if notifier:
                for item in items:
                    grade_id = item.get("grade_id")
                    if grade_id:
                        notifier.sent_grades.add(grade_id)
                notifier._save_sent_grades()
        else:
            await callback.message.answer("❌ Уведомления не отправлены.")
            if notifier:
                for item in items:
                    grade_id = item.get("grade_id")
                    if grade_id:
                        notifier.sent_grades.add(grade_id)
                notifier._save_sent_grades()

        user_data["pending_events"] = []
        user_data["events_prompt_pending"] = False
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await callback.answer()

    @dp.callback_query(F.data.in_({"ns_homework_send_all", "ns_homework_summary", "ns_homework_skip"}))
    async def ns_homework_decision(callback: CallbackQuery):
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id)
        items = user_data.get("pending_homework") or []
        if not items:
            await callback.message.answer("ℹ️ Нет ожидающих домашних заданий.")
            await callback.answer()
            return

        decision = callback.data
        notifier = runtime.netschool_user_notifiers.get(user_id)

        if decision in {"ns_homework_send_all", "ns_homework_summary"}:
            summary = _format_homework_summary(items)
            await callback.message.answer(
                "📝 <b>Список новых домашних заданий</b>\n\n" + summary,
                parse_mode="HTML"
            )
        else:
            await callback.message.answer("❌ Домашние задания не отправлены.")

        user_data["pending_homework"] = []
        user_data["homework_prompt_pending"] = False
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await callback.answer()

    @dp.message(F.chat.type == "private")
    async def ns_private_flow(message: Message):
        if not message.text or (message.text and message.text.startswith("/")):
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        state = user_data.get("state")

        # === Новые состояния: выбор региона и школы ===

        if state == "await_custom_url":
            url = message.text.strip()
            if not url.startswith(("http://", "https://")):
                await message.answer("❌ URL должен начинаться с http:// или https://\nПример: https://sgo.edu-74.ru")
                return
            user_data["netschool_url"] = url.rstrip("/")
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            set_netschool_user_state(user_id, "await_school_search")
            await message.answer(
                f"✅ URL: {url}\n\n"
                "🏫 Введите часть названия школы для поиска:\n"
                "Например: Лицей или Школа №1",
                reply_markup=_kb_back_cancel()
            )
            return

        if state == "await_school_search":
            query = message.text.strip()
            user_url = _get_user_ns_url(user_data)
            if not user_url:
                await message.answer("❌ URL не задан. Начните заново через /login.")
                set_netschool_user_state(user_id, None)
                return
            await message.answer("⏳ Ищу школы...")
            try:
                from netschoolpy import search_schools
                schools = await search_schools(user_url, query, proxy=ns_client._get_proxy_for_url(user_url))
            except Exception as e:
                err_str = str(e)
                if any(k in err_str.lower() for k in ("timeout", "timed out", "connect", "network", "unreachable", "refused", "name resol", "nodename", "temporary failure", "serverunavailable", "server unavailable")):
                    hint = (
                        "⚠️ Сервер НетШколы не ответил вовремя.\n\n"
                        "Возможные причины: временная недоступность сервера, проблемы сети или ограничения региона.\n\n"
                        "Попробуйте повторить поиск через несколько секунд."
                    )
                else:
                    hint = f"Ошибка: {err_str}"
                await message.answer(
                    f"❌ Ошибка поиска школ.\n\n{hint}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="ns_school_retry")],
                        [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")],
                    ])
                )
                return
            if not schools:
                await message.answer(
                    "❌ Школы не найдены. Попробуйте другой запрос.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="ns_school_retry")],
                        [InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")],
                    ])
                )
                return
            # Сохраняем результаты в кеш и строим клавиатуру с индексами
            names = [s.short_name or s.name for s in schools[:20]]
            runtime._SCHOOL_SEARCH_CACHE[user_id] = names
            rows: list[list[InlineKeyboardButton]] = []
            for idx, name in enumerate(names):
                rows.append([InlineKeyboardButton(text=f"🏫 {name}", callback_data=f"ns_school:{idx}")])
            rows.append([InlineKeyboardButton(text="🔄 Другой запрос", callback_data="ns_school_retry")])
            rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="ns_back_cancel")])
            kb = InlineKeyboardMarkup(inline_keyboard=rows)
            count = len(schools)
            await message.answer(
                f"🏫 Найдено школ: {count}\nВыберите вашу школу:",
                reply_markup=kb
            )
            return

        if state == "await_esia_login":
            user_data["login"] = message.text.strip()
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            set_netschool_user_state(user_id, "await_esia_password")
            await message.answer(
                "🔒 Теперь отправьте пароль от Госуслуг.\n"
                "Сообщение будет удалено сразу после получения.",
                reply_markup=_kb_back_cancel()
            )
            return

        if state == "await_esia_password":
            try:
                await message.delete()
            except Exception:
                pass
            user_data["password"] = message.text.strip()
            user_data["login_type"] = "esia"
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()

            user_url = _get_user_ns_url(user_data)
            if not user_url:
                await message.answer("❌ URL не настроен. Начните заново через /login.")
                set_netschool_user_state(user_id, None)
                return
            user_school = _get_user_ns_school(user_data)
            ns_client = _make_netschool(user_url)
            await message.answer("⏳ Вхожу через Госуслуги...")
            try:
                otp_cb = _make_esia_mfa_callback(user_id, bot)
                await ns_client.login_via_gosuslugi(
                    esia_login=user_data.get("login"),
                    esia_password=user_data.get("password"),
                    school=user_school or None,
                    timeout=60,
                    otp_callback=otp_cb,
                )
                try:
                    _apply_selected_student_to_client(ns_client, user_data)
                    _students, _sid, _ = await _sync_user_students_from_ns(ns_client, user_data, persist=False)
                    fio = await _fetch_student_name(ns_client)
                    if fio:
                        user_data["student_name"] = fio
                except Exception:
                    pass

                user_data["enabled"] = True
                user_data["updated_at"] = datetime.now().isoformat()
                save_netschool_users()
                set_netschool_user_state(user_id, None)
                await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
                name_part = f" ({user_data.get('student_name')})" if user_data.get("student_name") else ""
                await message.answer(f"✅ Успешный вход через Госуслуги{name_part}. Уведомления включены.")
            except Exception as e:
                error_name = type(e).__name__
                logger.warning(f"ESIA login failed for {user_id}: {error_name}: {e}")
                err_class = _classify_login_error(e)

                if err_class == "esia":
                    # Госуслуги недоступны — ставим retry
                    user_data["enabled"] = False
                    user_data["updated_at"] = datetime.now().isoformat()
                    save_netschool_users()
                    set_netschool_user_state(user_id, None)
                    await start_login_retry_task(user_id, bot)
                    await message.answer(
                        "⚠️ Сервер Госуслуг (ЕСИА) временно недоступен.\n"
                        "Я буду пытаться войти каждые 3 минуты и сообщу об успехе."
                    )
                elif err_class == "server":
                    user_data["enabled"] = False
                    user_data["updated_at"] = datetime.now().isoformat()
                    save_netschool_users()
                    set_netschool_user_state(user_id, None)
                    await start_login_retry_task(user_id, bot)
                    await message.answer(
                        "⚠️ Сервер журнала временно недоступен.\n"
                        "Я буду пытаться войти каждые 3 минуты и сообщу об успехе."
                    )
                else:
                    err_msg = str(e)
                    if "CAPTCHA" in err_msg or "captcha" in err_msg.lower():
                        hint = "\n\n⚠️ Слишком много попыток. Подождите немного и попробуйте снова."
                    else:
                        hint = ""
                    set_netschool_user_state(user_id, "await_esia_password")
                    await message.answer(
                        f"❌ Не удалось войти через Госуслуги.\n{err_msg[:300]}{hint}\n\n"
                        "Отправьте пароль повторно или нажмите «Назад».",
                        reply_markup=_kb_back_cancel()
                    )
            finally:
                try:
                    await _close_netschool_client(ns_client, do_logout=False)
                except Exception:
                    pass
            return

        if state == "await_esia_otp":
            # Пользователь прислал OTP-код для двухфакторной аутентификации ЕСИА
            try:
                await message.delete()
            except Exception:
                pass
            future = esia_otp_futures.pop(user_id, None)
            if future and not future.done():
                future.set_result(message.text.strip())
            else:
                await message.answer(
                    "⚠️ Время ожидания кода истекло или вход был отменён.\n"
                    "Попробуйте снова через /relogin.",
                )
                set_netschool_user_state(user_id, None)
            return

        if state and state.startswith("await_calc_target_"):
            try:
                grade = int(state.rsplit("_", 1)[1])
            except Exception:
                set_netschool_user_state(user_id, None)
                await message.answer("❌ Ошибка состояния. Откройте калькулятор заново.")
                return
            try:
                value = float(message.text.strip().replace(",", "."))
            except Exception:
                await message.answer(
                    "❌ Введите число, например: 4.60",
                    reply_markup=_kb_cancel_action(),
                )
                return
            if value < 0 or value > 5:
                await message.answer(
                    "❌ Порог должен быть в диапазоне от 0 до 5.",
                    reply_markup=_kb_cancel_action(),
                )
                return
            user_data[f"calc_target_{grade}"] = value
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            set_netschool_user_state(user_id, None)
            await message.answer(
                f"✅ Порог для оценки «{grade}» сохранён: <b>{value:.2f}</b>",
                parse_mode="HTML",
                reply_markup=_build_netschool_main_menu(user_data),
            )
            return

        if state == "await_bugreport":
            bug_text = message.text.strip()
            if len(bug_text) < 5:
                await message.answer(
                    "❌ Описание слишком короткое. Опишите проблему подробнее или нажмите «Отмена».",
                    reply_markup=_kb_cancel_action()
                )
                return
            user = message.from_user
            user_info = f"👤 От: {user.full_name}"
            if user.username:
                user_info += f" (@{user.username})"
            user_info += f" [ID: {user.id}]"
            report_msg = (
                "🐛 <b>НОВЫЙ БАГ-РЕПОРТ</b>\n\n"
                f"{user_info}\n\n"
                f"📝 Описание:\n{bug_text}\n\n"
                f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            )
            try:
                await runtime.log_bot.send_message(TG_ADMIN_ID, report_msg, parse_mode="HTML")
                set_netschool_user_state(user_id, None)
                await message.answer(
                    "✅ Спасибо! Сообщение отправлено администратору.",
                    reply_markup=_build_netschool_main_menu(user_data)
                )
            except Exception:
                await message.answer(
                    "❌ Ошибка при отправке сообщения. Попробуйте позже.",
                    reply_markup=_kb_cancel_action()
                )
            return

        if state == "await_login":
            user_data["login"] = message.text.strip()
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            set_netschool_user_state(user_id, "await_password")
            await message.answer("Теперь отправьте пароль от журнала.", reply_markup=_kb_back_to_login())
            return

        if state == "await_password":
            user_data["password"] = message.text.strip()
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()

            user_url = _get_user_ns_url(user_data)
            user_school = _get_user_ns_school(user_data)
            if not user_url or not user_school:
                await message.answer("❌ Регион/школа не настроены. Начните заново через /login.")
                set_netschool_user_state(user_id, None)
                return
            ns_client = _make_netschool(user_url)
            await message.answer("⏳ Пытаюсь войти в журнал...")
            try:
                await ns_client.login(
                    user_name=user_data.get("login"),
                    password=user_data.get("password"),
                    school=user_school
                )
                try:
                    _apply_selected_student_to_client(ns_client, user_data)
                    _students, _sid, _ = await _sync_user_students_from_ns(ns_client, user_data, persist=False)
                    fio = await _fetch_student_name(ns_client)
                    if fio:
                        user_data["student_name"] = fio
                except Exception:
                    pass
                try:
                    await _close_netschool_client(ns_client, do_logout=False)
                except Exception:
                    pass

                user_data["enabled"] = True
                user_data["updated_at"] = datetime.now().isoformat()
                save_netschool_users()
                set_netschool_user_state(user_id, None)
                await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
                await message.answer("✅ Успешный вход. Уведомления включены.")
            except Exception as e:
                error_name = type(e).__name__
                logger.warning(f"NetSchool login failed for {user_id}: {error_name}: {e}")

                if is_server_unavailable_error(e):
                    user_data["enabled"] = False
                    user_data["updated_at"] = datetime.now().isoformat()
                    save_netschool_users()
                    set_netschool_user_state(user_id, None)
                    await start_login_retry_task(user_id, bot)
                    await message.answer(
                        "⚠️ Сервер журнала временно недоступен.\n"
                        "Я буду пытаться войти каждые 3 минуты и сообщу об успехе."
                    )
                else:
                    set_netschool_user_state(user_id, "await_password")
                    await message.answer(
                        "❌ Не удалось войти в журнал. Проверьте логин/пароль и попробуйте снова.\n"
                        "Можно нажать «Назад», чтобы изменить логин.",
                        reply_markup=_kb_back_to_login()
                    )
            return

        date_picker = user_data.get("date_picker")
        if date_picker in ("dz", "rasp"):
            selected = _parse_date_input(message.text)
            if not selected:
                await message.answer("❌ Неверный формат даты. Пример: 28.02 или 28.02.2026")
                return
            user_data["date_picker"] = None
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            if date_picker == "dz":
                await _send_homework_for_dates(message, {selected}, "📚 Домашнее задание (на выбранную дату):", user_id=user_id)
            else:
                await _send_schedule_for_dates(message, {selected}, "🗓 Расписание на выбранную дату:", user_id=user_id)
            return

