"""Главное меню, панель управления, калькулятор оценок, профиль."""

from ._common import *  # noqa: F401,F403
from ._common import *  # noqa: F401,F403


def register(dp: Dispatcher, bot: Bot) -> None:
    @dp.message(Command("start", "help", "menu"))
    async def ns_cmd_start(message: Message):
        if message.chat.type != "private":
            await message.reply("📩 Напишите мне в личные сообщения для настройки оценок.")
            return

        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)

        intro = (
            "Привет! Я помогаю с Сетевым Городом и присылаю уведомления сюда, в личку.\n\n"
            "<b>Что можно сделать через меню ниже:</b>\n"
            "• подключить или переподключить журнал\n"
            "• посмотреть оценки, домашку, расписание и почту\n"
            "• включить или выключить уведомления\n"
            "• поменять интервал проверки\n"
            "• отправить баг-репорт\n\n"
            "Если журнал ещё не подключён, начните с /login."
        )

        await message.answer(
            intro,
            parse_mode="HTML",
            reply_markup=_build_reply_keyboard()
        )
        await message.answer(
            "Главное меню NetSchool",
            reply_markup=_build_netschool_main_menu(user_data)
        )

    @dp.message(F.text == "⚙️ Меню")
    async def ns_cmd_menu_text(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        await message.answer("Главное меню NetSchool", reply_markup=_build_netschool_main_menu(user_data))

    @dp.message(F.text == "📱 Открыть дневник")
    async def ns_cmd_diary_text(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        token = _issue_netschool_miniapp_token(user_id)
        miniapp_url = _build_netschool_miniapp_url(token)
        if not miniapp_url:
            await message.answer("📱 Мини-приложение ещё не настроено: отсутствует NETSCHOOL_MINIAPP_BASE_URL.")
            return
        if miniapp_url.startswith("https://"):
            reply_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть дневник", web_app=WebAppInfo(url=f"{miniapp_url}&startapp=diary#diary"))]])
        else:
            reply_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть дневник", url=f"{miniapp_url}&startapp=diary#diary")]])
        await message.answer("📱 Откройте дневник кнопкой ниже:", reply_markup=reply_markup)

    @dp.callback_query(F.data == "ns_open_settings")
    async def ns_open_settings_cb(callback: CallbackQuery):
        if callback.message.chat.type != "private":
            await callback.answer()
            return
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id, callback.from_user.full_name)
        await callback.message.answer(
            _build_settings_text(user_data),
            parse_mode="HTML",
            reply_markup=_build_settings_keyboard(user_data)
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("ns_menu:"))
    async def ns_menu_action(callback: CallbackQuery):
        if callback.message.chat.type != "private":
            await callback.answer()
            return
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id, callback.from_user.full_name)
        action = (callback.data or "").split(":", 1)[1]

        async def _send_miniapp_entrypoint(text: str, *, tab: str = "diary", button_text: str = "Открыть дневник") -> None:
            token = _issue_netschool_miniapp_token(user_id)
            miniapp_url = _build_netschool_miniapp_url(token)
            if not miniapp_url:
                await callback.message.answer("📱 Мини-приложение ещё не настроено: отсутствует NETSCHOOL_MINIAPP_BASE_URL.")
                return
            if tab:
                miniapp_url = f"{miniapp_url}&startapp={tab}#{tab}"
            if miniapp_url.startswith("https://"):
                reply_markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=button_text, web_app=WebAppInfo(url=miniapp_url))]
                ])
            else:
                reply_markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=button_text, url=miniapp_url)]
                ])
            await callback.message.answer(text, reply_markup=reply_markup)

        async def _send_pwa_link() -> None:
            token = _issue_netschool_pwa_token(user_id)
            pwa_url = _build_netschool_miniapp_url(token)
            if not pwa_url:
                await callback.message.answer("🔗 PWA-ссылка ещё не настроена: отсутствует NETSCHOOL_MINIAPP_BASE_URL.")
                return
            reply_markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Открыть PWA-ссылку", url=pwa_url)]
            ])
            await callback.message.answer(
                "🔗 Ссылка для установки PWA готова. Откройте её в Safari на iPhone и добавьте на экран Домой.\n\n" + pwa_url,
                reply_markup=reply_markup,
            )

        async def _get_official_total_marks(ns_client: NetSchool):
            if hasattr(ns_client, "total_marks"):
                return await ns_client.total_marks()
            if hasattr(ns_client, "totals_marks"):
                return await ns_client.totals_marks()
            raise RuntimeError("Текущая версия netschoolpy не поддерживает официальный отчёт итоговых оценок.")

        if action == "hub":
            await _render_netschool_control_center(callback.message, user_id, edit=True, display_name=callback.from_user.full_name)
        elif action == "status":
            await _send_miniapp_entrypoint("📊 Статус и учебные данные теперь открываются в мини-приложении.")
        elif action == "miniapp":
            await _send_miniapp_entrypoint("📱 Откройте дневник кнопкой ниже.", tab="diary", button_text="Открыть дневник")
        elif action == "pwalink":
            await _send_pwa_link()
        elif action == "profile":
            await callback.message.answer(
                _build_profile_text(user_data, user_id),
                parse_mode="HTML",
                reply_markup=_build_netschool_main_menu(user_data)
            )
        elif action == "students":
            ns = await _get_ns_client(callback.message, user_id=user_id)
            if ns:
                try:
                    students = getattr(ns, "students", None) or []
                    if not students:
                        await callback.message.answer("Ученики не найдены.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="ns_menu:hub")]]))
                    else:
                        buttons = []
                        for s in students:
                            mark = "✅ " if getattr(ns, '_student_id', None) == s.id else ""
                            buttons.append([InlineKeyboardButton(text=f"{mark}{s.name}", callback_data=f"ns_child:{s.id}")])
                        buttons.append([InlineKeyboardButton(text="↩️ Центр", callback_data="ns_menu:hub")])
                        await callback.message.answer("👥 Выберите ученика:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
                except Exception as e:
                    await callback.message.answer(f"Ошибка при получении списка учеников: {e}")

        elif action == "settings":
            await callback.message.answer(
                _build_settings_text(user_data),
                parse_mode="HTML",
                reply_markup=_build_settings_keyboard(user_data)
            )
        elif action == "mystats":
            await _send_miniapp_entrypoint("📈 Статистика и предметы уже собраны в мини-приложении.", tab="grades", button_text="Открыть оценки")
        elif action == "weeksummary":
            await _send_miniapp_entrypoint("🗓 Сводка недели и оценки доступны в мини-приложении.", tab="grades", button_text="Открыть оценки")
        elif action == "dz" or action == "homework":
            await _send_miniapp_entrypoint("📝 Домашние задания теперь открываются в мини-приложении.", tab="homework", button_text="Открыть ДЗ")
        elif action == "rasp":
            await _send_miniapp_entrypoint("🗓 Расписание теперь открывается в мини-приложении.", tab="diary", button_text="Открыть дневник")
        elif action == "interval":
            current_interval = _clamp_interval(int(user_data.get("check_interval") or CHECK_INTERVAL))
            await callback.message.answer(
                f"⏱ Текущий интервал проверки: {current_interval // 60} мин.\nВыберите готовое значение или отправьте /interval 7м вручную.",
                reply_markup=_build_interval_presets_keyboard()
            )
        elif action == "subjectfilter":
            status_msg = await callback.message.answer("⌛ Получаю список предметов...")
            ns = await _get_ns_client(callback.message, user_id=user_id)
            if ns:
                try:
                    quarter_start = _current_quarter_start()
                    today_d = datetime.now(dt_timezone(timedelta(hours=3))).date()
                    weeks_back = max(4, (today_d - quarter_start).days // 7 + 2)
                    days = await _fetch_diary_days(ns, weeks_back=weeks_back, weeks_forward=2)
                    subjects, _ = _collect_grades(days, since_date=quarter_start)
                    subjects = sorted(subjects)
                    if subjects:
                        runtime.GRADES_SUBJECTS_CACHE[user_id] = {
                            "subjects": subjects,
                            "ts": datetime.now().isoformat()
                        }
                        selected = get_user_subject_include_titles(user_data)
                        await callback.message.answer(
                            "📘 Выберите предметы, по которым нужны уведомления.\nЕсли ничего не выбрано, приходят все предметы.",
                            reply_markup=_build_subject_filter_keyboard(subjects, selected, page=0)
                        )
                    else:
                        await callback.message.answer("✅ Предметы пока не найдены.")
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
        elif action == "quiethours":
            await callback.message.answer(
                "🌙 Выберите тихие часы. В это время уведомления об оценках и авто-сводка не отправляются.",
                reply_markup=_build_quiet_hours_keyboard()
            )
        elif action == "bugreport":
            set_netschool_user_state(user_id, "await_bugreport")
            await callback.message.answer(
                "🐛 Опишите проблему следующим сообщением.\n\nНажмите «Отмена», если передумали.",
                reply_markup=_kb_cancel_action()
            )
        elif action == "mail":
            await _send_miniapp_entrypoint("📬 Почта теперь открывается в мини-приложении.", tab="mail", button_text="Открыть почту")
        elif action == "grades":
            selected_q = user_data.get("selected_quarter", None)
            q_text = f" (Четверть {selected_q})" if selected_q else " (Текущая четверть)"
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="1️⃣", callback_data="ns_menu:set_q_1"),
                    InlineKeyboardButton(text="2️⃣", callback_data="ns_menu:set_q_2"),
                    InlineKeyboardButton(text="3️⃣", callback_data="ns_menu:set_q_3"),
                    InlineKeyboardButton(text="4️⃣", callback_data="ns_menu:set_q_4"),
                    InlineKeyboardButton(text="🔄", callback_data="ns_menu:set_q_0"),
                ],
                [InlineKeyboardButton(text=f"📊 Итоги и средние{q_text}", callback_data="ns_menu:grades_avg")],
                [InlineKeyboardButton(text="🏆 Итоговые (официальные)", callback_data="ns_menu:grades_totals")],
                [InlineKeyboardButton(text="🧮 Калькулятор", callback_data="ns_menu:grades_calc_start")],
                [InlineKeyboardButton(text=f"📚 Оценки по предметам{q_text}", callback_data="ns_menu:grades_list")],
                [InlineKeyboardButton(text="📱 Открыть в мини-приложении", callback_data="ns_menu:miniapp")],
                [InlineKeyboardButton(text="↩️ Центр", callback_data="ns_menu:hub")],
            ])
            try:
                await callback.message.edit_text("📚 <b>Оценки и успеваемость</b>\nВыберите нужный раздел или четверть:", parse_mode="HTML", reply_markup=kb)
            except Exception:
                await callback.message.answer("📚 <b>Оценки и успеваемость</b>\nВыберите нужный раздел или четверть:", parse_mode="HTML", reply_markup=kb)
        elif action.startswith("set_q_"):
            q_val = int(action.split("_")[-1])
            if q_val == 0:
                user_data.pop("selected_quarter", None)
            else:
                user_data["selected_quarter"] = q_val
            
            selected_q = user_data.get("selected_quarter", None)
            q_text = f" (Четверть {selected_q})" if selected_q else " (Текущая четверть)"
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="1️⃣", callback_data="ns_menu:set_q_1"),
                    InlineKeyboardButton(text="2️⃣", callback_data="ns_menu:set_q_2"),
                    InlineKeyboardButton(text="3️⃣", callback_data="ns_menu:set_q_3"),
                    InlineKeyboardButton(text="4️⃣", callback_data="ns_menu:set_q_4"),
                    InlineKeyboardButton(text="🔄", callback_data="ns_menu:set_q_0"),
                ],
                [InlineKeyboardButton(text=f"📊 Итоги и средние{q_text}", callback_data="ns_menu:grades_avg")],
                [InlineKeyboardButton(text="🏆 Итоговые (официальные)", callback_data="ns_menu:grades_totals")],
                [InlineKeyboardButton(text="🧮 Калькулятор", callback_data="ns_menu:grades_calc_start")],
                [InlineKeyboardButton(text=f"📚 Оценки по предметам{q_text}", callback_data="ns_menu:grades_list")],
                [InlineKeyboardButton(text="📱 Открыть в мини-приложении", callback_data="ns_menu:miniapp")],
                [InlineKeyboardButton(text="↩️ Центр", callback_data="ns_menu:hub")],
            ])
            await callback.message.edit_text("📚 <b>Оценки и успеваемость</b>\nВыберите нужный раздел или четверть:", parse_mode="HTML", reply_markup=kb)
            await callback.answer(f"Выбрана {'четверть ' + str(selected_q) if selected_q else 'текущая четверть'}")
        elif action == "grades_list":
            ns = await _get_ns_client(callback.message, user_id=user_id)
            if not ns:
                return
            await callback.message.edit_text("⌛ Загрузка списка предметов...")
            try:
                quarter_start = _quarter_start_for_user(user_data)
                today_d = datetime.now(dt_timezone(timedelta(hours=3))).date()
                days_diff = (today_d - quarter_start).days
                weeks_back = max(4, abs(days_diff) // 7 + 2) if days_diff > 0 else 40
                days = await _fetch_diary_days(ns, weeks_back=weeks_back, weeks_forward=2)
                subjects, _ = _collect_grades(days, since_date=quarter_start)
                subjects = sorted(subjects)
                if not subjects:
                    await callback.message.edit_text("✅ Предметы не найдены.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="ns_menu:grades")]]))
                    return
                runtime.GRADES_SUBJECTS_CACHE[user_id] = {
                    "subjects": subjects,
                    "ts": datetime.now().isoformat()
                }
                keyboard = _build_grades_subjects_keyboard(subjects, page=0)
                await callback.message.edit_text("📚 Выберите предмет:", reply_markup=keyboard)
            except Exception as e:
                await callback.message.edit_text(f"Ошибка загрузки: {e}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="ns_menu:grades")]]))

        elif action == "grades_totals":
            ns = await _get_ns_client(callback.message, user_id=user_id)
            if not ns: return
            await callback.message.edit_text("⌛ Скачиваю официальный отчёт 'Итоговые оценки'...")
            try:
                marks = await _get_official_total_marks(ns)
                lines_res = ["🏆 <b>Итоговые оценки (StudentTotalMarks)</b>\n"]
                if not marks:
                    lines_res.append("Нет данных.")
                else:
                    for m in marks:
                        p_str = ", ".join([str(x) if x else "-" for x in m.period_marks]) if m.period_marks else "-"
                        fin_str = []
                        if m.year_mark: fin_str.append(f"год: <b>{m.year_mark}</b>")
                        if m.exam_mark: fin_str.append(f"экз: <b>{m.exam_mark}</b>")
                        if m.final_mark: fin_str.append(f"итог: <b>{m.final_mark}</b>")
                        add_str = f" | {' '.join(fin_str)}" if fin_str else ""
                        lines_res.append(f"• <b>{m.subject}</b>\n   Четверти: [{p_str}]{add_str}\n")

                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="ns_menu:grades")]])
                await callback.message.edit_text("\n".join(lines_res), parse_mode="HTML", reply_markup=kb)
            except Exception as e:
                if "не поддерживает официальный отчёт" in str(e):
                    try:
                        # Fallback: estimate quarter grades from diary marks when API lacks totals endpoint.
                        days = await _fetch_diary_days(ns, weeks_back=40, weeks_forward=2)
                        _subjects, entries = _collect_grades(days, since_date=None)
                        per_subject: dict[str, dict[int, list[tuple[int, int]]]] = {}
                        for subj, d, _title, mark, weight in entries:
                            val = _extract_mark_value(mark)
                            try:
                                num = int(val)
                            except (TypeError, ValueError):
                                continue
                            if d.month in (9, 10):
                                q = 1
                            elif d.month in (11, 12):
                                q = 2
                            elif d.month in (1, 2, 3):
                                q = 3
                            else:
                                q = 4
                            per_subject.setdefault(subj, {1: [], 2: [], 3: [], 4: []})[q].append((num, weight or 1))

                        lines_res = ["🏆 <b>Итоговые оценки</b>", "<i>Официальный отчёт в вашей школе не поддерживается, показываю расчёт по дневнику.</i>\n"]
                        for subj in sorted(per_subject.keys()):
                            q_marks: list[str] = []
                            for q in (1, 2, 3, 4):
                                pairs = per_subject[subj][q]
                                if not pairs:
                                    q_marks.append("-")
                                    continue
                                sw = sum(w for _, w in pairs)
                                if sw <= 0:
                                    q_marks.append("-")
                                    continue
                                avg = sum(m * w for m, w in pairs) / sw
                                # Округляем 4.5 -> 5 (математически, а не банковски)
                                import math
                                q_marks.append(str(math.floor(avg + 0.5)))
                            
                            # Убираем лишние "-" с конца, чтобы выглядело как в NetSchool
                            while q_marks and q_marks[-1] == "-":
                                q_marks.pop()
                            if not q_marks:
                                q_marks = ["-"]

                            lines_res.append(f"• <b>{subj}</b>\n   Четверти: {', '.join(q_marks)}\n")

                        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="ns_menu:grades")]])
                        await callback.message.edit_text("\n".join(lines_res), parse_mode="HTML", reply_markup=kb)
                        await callback.answer()
                        return
                    except Exception as fallback_exc:
                        e = fallback_exc
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="ns_menu:grades")]])
                await callback.message.edit_text(f"Ошибка загрузки отчёта: {e}", reply_markup=kb)

        elif action == "grades_avg":
            ns = await _get_ns_client(callback.message, user_id=user_id)
            if not ns:
                return
            await callback.message.edit_text("⌛ Вычисляю средние баллы...")
            try:
                quarter_start = _quarter_start_for_user(user_data)
                today_d = datetime.now(dt_timezone(timedelta(hours=3))).date()
                days_diff = (today_d - quarter_start).days
                weeks_back = max(4, abs(days_diff) // 7 + 2) if days_diff > 0 else 40
                days = await _fetch_diary_days(ns, weeks_back=weeks_back, weeks_forward=2)
                subjects, entries = _collect_grades(days, since_date=quarter_start)
                
                # Compute averages
                q_text = f" (Четверть {user_data.get('selected_quarter')})" if user_data.get("selected_quarter") else " (Текущая четверть)"
                lines = [f"📊 <b>Средний балл по предметам{q_text}</b>\n"]
                subj_data = {}
                for subj, _, _, mark, weight in entries:
                    if mark is None: continue
                    val = _extract_mark_value(mark)
                    try:
                        num = int(val)
                    except (ValueError, TypeError):
                        continue
                    if subj not in subj_data:
                        subj_data[subj] = {"sum": 0, "weight": 0}
                    subj_data[subj]["sum"] += num * weight
                    subj_data[subj]["weight"] += weight
                
                for subj in sorted(subjects):
                    if subj in subj_data and subj_data[subj]["weight"] > 0:
                        avg = subj_data[subj]["sum"] / subj_data[subj]["weight"]
                        lines.append(f"• {subj}: <b>{avg:.2f}</b>")
                    else:
                        lines.append(f"• {subj}: <i>нет оценок</i>")
                        
                text = "\n".join(lines)
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="ns_menu:grades")]])
                await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            except Exception as e:
                await callback.message.edit_text(f"Ошибка вычисления: {e}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="ns_menu:grades")]]))

        elif action == "calc_targets":
            target_5 = float(user_data.get("calc_target_5", 4.50))
            target_4 = float(user_data.get("calc_target_4", 3.50))
            target_3 = float(user_data.get("calc_target_3", 2.50))
            target_2 = float(user_data.get("calc_target_2", 1.50))
            text = (
                "⚙️ <b>Настройка порогов среднего балла</b>\n\n"
                f"Для оценки «5»: <b>{target_5:.2f}</b>\n"
                f"Для оценки «4»: <b>{target_4:.2f}</b>\n"
                f"Для оценки «3»: <b>{target_3:.2f}</b>\n"
                f"Для оценки «2»: <b>{target_2:.2f}</b>\n\n"
                "Выберите оценку ниже и отправьте один раз новый порог (например: 4.60)."
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Изменить 5", callback_data="ns_calc_target_set:5"),
                    InlineKeyboardButton(text="Изменить 4", callback_data="ns_calc_target_set:4"),
                ],
                [
                    InlineKeyboardButton(text="Изменить 3", callback_data="ns_calc_target_set:3"),
                    InlineKeyboardButton(text="Изменить 2", callback_data="ns_calc_target_set:2"),
                ],
                [InlineKeyboardButton(text="↩️ Назад", callback_data="ns_menu:grades_calc_start")],
            ])
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

        elif action == "grades_calc_start":
            ns = await _get_ns_client(callback.message, user_id=user_id)
            if not ns: return
            await callback.message.edit_text("⌛ Загрузка...")
            try:
                quarter_start = _quarter_start_for_user(user_data)
                today_d = datetime.now(dt_timezone(timedelta(hours=3))).date()
                days_diff = (today_d - quarter_start).days
                weeks_back = max(4, abs(days_diff) // 7 + 2) if days_diff > 0 else 40
                days = await _fetch_diary_days(ns, weeks_back=weeks_back, weeks_forward=2)
                subjects, entries = _collect_grades(days, since_date=quarter_start)
                subjects = sorted([s for s in subjects if s])
                
                if not subjects:
                    await callback.message.edit_text("✅ Предметы не найдены.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="ns_menu:grades")]]))
                    return
                
                # Pack the calculate subjects kb
                rows = []
                row = []
                for idx, subj in enumerate(subjects):
                    row.append(InlineKeyboardButton(text=subj, callback_data=f"ns_calc:{idx}"))
                    if len(row) == 2:
                        rows.append(row)
                        row = []
                if row: rows.append(row)
                rows.append([InlineKeyboardButton(text="🆕 С нуля", callback_data="ns_calc:new")])
                rows.append([InlineKeyboardButton(text="↩️ Назад", callback_data="ns_menu:grades")])
                
                # Save context
                runtime.GRADES_SUBJECTS_CACHE[user_id] = {
                    "subjects": subjects,
                    "entries": entries,
                    "type": "calc_select"
                }
                await callback.message.edit_text("🧮 <b>Калькулятор баллов</b>\n\nВыберите предмет:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
            except Exception as e:
                await callback.message.edit_text(f"Ошибка загрузки: {e}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="ns_menu:grades")]]))

        elif action == "on":
            user_data["enabled"] = True
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
            await callback.message.answer("✅ Уведомления включены.", reply_markup=_build_netschool_main_menu(user_data))
        elif action == "off":
            user_data["enabled"] = False
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            await stop_user_grade_task(user_id)
            await callback.message.answer("🔕 Уведомления выключены.", reply_markup=_build_netschool_main_menu(user_data))
        elif action == "weekly_on":
            user_data["weekly_summary_enabled"] = True
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            await callback.message.answer("✅ Автосводка включена.", reply_markup=_build_netschool_main_menu(user_data))
        elif action == "weekly_off":
            user_data["weekly_summary_enabled"] = False
            user_data["updated_at"] = datetime.now().isoformat()
            save_netschool_users()
            await callback.message.answer("🔕 Автосводка отключена.", reply_markup=_build_netschool_main_menu(user_data))
        elif action == "login":
            set_netschool_user_state(user_id, "await_region")
            await callback.message.answer("🌍 Выберите регион:", reply_markup=_build_region_keyboard())
        elif action == "relogin":
            await callback.message.answer("Используйте /relogin для безопасного повторного входа.")

        await callback.answer()

    @dp.callback_query(F.data.startswith("ns_calc:"))
    async def ns_calc_action(callback: CallbackQuery):
        if callback.message.chat.type != "private":
            await callback.answer()
            return
        user_id = callback.from_user.id
        parts = callback.data.split(":")
        # Format: ns_calc:idx:c5:c4:c3:c2
        cache = runtime.GRADES_SUBJECTS_CACHE.get(user_id)
        if not cache or cache.get("type") != "calc_select":
            await callback.answer("Сессия истекла. Откройте меню заново.")
            return
            
        try:
            raw_idx = parts[1]
            from_scratch = raw_idx == "new"
            subj_idx = -1 if from_scratch else int(raw_idx)
            c5 = int(parts[2]) if len(parts) > 2 else 0
            c4 = int(parts[3]) if len(parts) > 3 else 0
            c3 = int(parts[4]) if len(parts) > 4 else 0
            c2 = int(parts[5]) if len(parts) > 5 else 0
        except (ValueError, IndexError):
            await callback.answer("Ошибка данных.")
            return

        subjects = cache.get("subjects", [])
        if (not from_scratch) and (subj_idx < 0 or subj_idx >= len(subjects)):
            await callback.answer("Предмет не найден.")
            return

        subject = "С нуля" if from_scratch else subjects[subj_idx]
        entries = cache.get("entries", [])
        
        # Original sum
        osum = 0
        ow = 0
        ocount = 0
        if not from_scratch:
            for s, _, _, mark, weight in entries:
                if s != subject or mark is None:
                    continue
                val = _extract_mark_value(mark)
                try:
                    num = int(val)
                    osum += num * weight
                    ow += weight
                except (ValueError, TypeError):
                    continue
                ocount += 1
                
        # Simulated additions
        tsum = osum + (c5 * 5) + (c4 * 4) + (c3 * 3) + (c2 * 2)
        tw = ow + c5 + c4 + c3 + c2
        
        o_avg = (osum / ow) if ow > 0 else 0
        t_avg = (tsum / tw) if tw > 0 else 0
        
        lines = [
            f"🧮 <b>Калькулятор оценок</b>",
            f"Предмет: <b>{subject}</b>",
            "",
            f"Текущий балл: <b>{o_avg:.2f}</b> (оценок: {ocount})",
            "",
            "Добавлено в расчёт:",
            f"• «5»: <b>{c5}</b>",
            f"• «4»: <b>{c4}</b>",
            f"• «3»: <b>{c3}</b>",
            f"• «2»: <b>{c2}</b>",
        ]
        
        if (tw - ow) > 0:
            lines.append(f"С прогнозом: <b>{t_avg:.2f}</b>")
            sims = []
            if c5: sims.append(f"{c5}× «5»")
            if c4: sims.append(f"{c4}× «4»")
            if c3: sims.append(f"{c3}× «3»")
            if c2: sims.append(f"{c2}× «2»")
            lines.append(f"<i>Добавлено: {', '.join(sims)}</i>")
            
        # Target suggestions
        user_data = get_netschool_user(user_id)
        target_5 = float(user_data.get("calc_target_5", 4.50))
        target_4 = float(user_data.get("calc_target_4", 3.50))
        target_3 = float(user_data.get("calc_target_3", 2.50))
        target_2 = float(user_data.get("calc_target_2", 1.50))
        
        if t_avg < target_5:
            # Need to reach target_5
            needed_5 = 0
            curr_s = tsum
            curr_w = tw
            while (curr_w == 0) or ((curr_s / curr_w) < target_5):
                curr_s += 5
                curr_w += 1
                needed_5 += 1
            if needed_5 > 0:
                lines.append(f"\nДо пятерки ({target_5:.2f}) нужно пятерок: <b>{needed_5}</b>")
        elif t_avg < target_4:
            needed_4 = 0
            curr_s = tsum
            curr_w = tw
            while (curr_w == 0) or ((curr_s / curr_w) < target_4):
                curr_s += 4
                curr_w += 1
                needed_4 += 1
            if needed_4 > 0:
                lines.append(f"\nДо четверки ({target_4:.2f}) нужно четверок: <b>{needed_4}</b>")
        elif t_avg < target_3:
            needed_3 = 0
            curr_s = tsum
            curr_w = tw
            while (curr_w == 0) or ((curr_s / curr_w) < target_3):
                curr_s += 3
                curr_w += 1
                needed_3 += 1
            if needed_3 > 0:
                lines.append(f"\nДо тройки ({target_3:.2f}) нужно троек: <b>{needed_3}</b>")
        elif t_avg < target_2:
            needed_2 = 0
            curr_s = tsum
            curr_w = tw
            while (curr_w == 0) or ((curr_s / curr_w) < target_2):
                curr_s += 2
                curr_w += 1
                needed_2 += 1
            if needed_2 > 0:
                lines.append(f"\nДо двойки ({target_2:.2f}) нужно двоек: <b>{needed_2}</b>")
                
        def mk_data(dc5=0, dc4=0, dc3=0, dc2=0):
            nc5 = max(0, c5 + dc5)
            nc4 = max(0, c4 + dc4)
            nc3 = max(0, c3 + dc3)
            nc2 = max(0, c2 + dc2)
            idx_part = "new" if from_scratch else str(subj_idx)
            return f"ns_calc:{idx_part}:{nc5}:{nc4}:{nc3}:{nc2}"
            
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="+5", callback_data=mk_data(dc5=1)),
                InlineKeyboardButton(text="+4", callback_data=mk_data(dc4=1)),
                InlineKeyboardButton(text="+3", callback_data=mk_data(dc3=1)),
                InlineKeyboardButton(text="+2", callback_data=mk_data(dc2=1)),
            ],
            [
                InlineKeyboardButton(text="-5", callback_data=mk_data(dc5=-1)),
                InlineKeyboardButton(text="-4", callback_data=mk_data(dc4=-1)),
                InlineKeyboardButton(text="-3", callback_data=mk_data(dc3=-1)),
                InlineKeyboardButton(text="-2", callback_data=mk_data(dc2=-1)),
            ],
            [
                InlineKeyboardButton(text="⚙️ Настроить пороги", callback_data="ns_menu:calc_targets")
            ],
            [InlineKeyboardButton(text="🔄 Сбросить", callback_data=mk_data(-c5, -c4, -c3, -c2))],
            [InlineKeyboardButton(text="↩️ К предметам", callback_data="ns_menu:grades_calc_start")]
        ])
        
        await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)

    @dp.callback_query(F.data.startswith("ns_calc_target_set:"))
    async def ns_calc_target_set(callback: CallbackQuery):
        if callback.message.chat.type != "private":
            await callback.answer()
            return
        user_id = callback.from_user.id
        try:
            grade = int((callback.data or "").split(":", 1)[1])
        except Exception:
            await callback.answer("Ошибка данных")
            return
        if grade not in (5, 4, 3, 2):
            await callback.answer("Поддерживаются только 5, 4, 3, 2")
            return
        set_netschool_user_state(user_id, f"await_calc_target_{grade}")
        await callback.message.answer(
            f"Введите новый порог для оценки «{grade}» (например: 4.60).",
            reply_markup=_kb_cancel_action(),
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("ns_child:"))
    async def ns_child_action(callback: CallbackQuery):
        if callback.message.chat.type != "private":
            await callback.answer()
            return
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id)
        try:
            target_id = int((callback.data or "").split(":", 1)[1])
        except ValueError:
            await callback.answer("Ошибка: неверный ID")
            return
        ns = await _get_ns_client(callback.message, user_id=user_id)
        if ns:
            try:
                student = await ns.switch_student(target_id)
                user_data["netschool_student_id"] = target_id
                save_netschool_users()
                
                # Refresh session implicitly in cache by updating it
                cached = NETSCHOOL_SESSION_CACHE.get(user_id)
                if cached:
                    cached["client"] = ns
                    cached["last_used"] = datetime.now()
                    
                await callback.message.edit_text(f"✅ Аккаунт переключен на ученика: {student.name}")
                await _render_netschool_control_center(callback.message, user_id, edit=False, display_name=callback.from_user.full_name)
            except Exception as e:
                await callback.answer(f"Ошибка переключения: {e}", show_alert=True)
        else:
            await callback.answer("Ошибка клиента. Перезайдите.", show_alert=True)

    @dp.callback_query(F.data.startswith("ns_panel:"))
    async def ns_panel_action(callback: CallbackQuery):
        if callback.message.chat.type != "private":
            await callback.answer()
            return
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id, callback.from_user.full_name)
        action = (callback.data or "").split(":", 1)[1]

        if action == "refresh":
            await _render_netschool_control_center(callback.message, user_id, edit=True, display_name=callback.from_user.full_name)
            await callback.answer("Обновлено")
            return
        if action == "menu":
            await callback.message.edit_text(
                "Главное меню NetSchool",
                reply_markup=_build_netschool_main_menu(user_data)
            )
            await callback.answer()
            return
        if action == "child":
            students = _get_available_students(user_data)
            if len(students) < 2:
                await callback.message.answer(
                    "ℹ️ В профиле найден только один ребёнок.",
                    reply_markup=_build_netschool_main_menu(user_data),
                )
                await callback.answer()
                return
            selected_id = _safe_int(user_data.get("selected_student_id"))
            selected_name = ""
            for student in students:
                if selected_id is not None and student["id"] == selected_id:
                    selected_name = student["name"]
                    break
            if not selected_name:
                selected_name = user_data.get("student_name") or students[0]["name"]
            await callback.message.answer(
                "👶 <b>Выберите ребёнка</b>\n\n"
                f"Сейчас: {html.escape(selected_name)}",
                parse_mode="HTML",
                reply_markup=_build_student_switch_keyboard(user_data),
            )
            await callback.answer()
            return

        if not action.startswith("toggle:"):
            await callback.answer()
            return

        toggle_key = action.split(":", 1)[1]
        if toggle_key == "enabled":
            new_val = not bool(user_data.get("enabled"))
            user_data["enabled"] = new_val
            if new_val:
                await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
            else:
                await stop_user_grade_task(user_id)
        elif toggle_key == "mail":
            user_data["notify_mail"] = not bool(user_data.get("notify_mail", True))
        elif toggle_key == "changes":
            user_data["notify_changes"] = not bool(user_data.get("notify_changes", True))
        elif toggle_key == "deletes":
            user_data["notify_deletes"] = not bool(user_data.get("notify_deletes", True))
        elif toggle_key == "weekly":
            user_data["weekly_summary_enabled"] = not bool(user_data.get("weekly_summary_enabled"))
        else:
            await callback.answer("Неизвестная настройка", show_alert=True)
            return

        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await _render_netschool_control_center(callback.message, user_id, edit=True, display_name=callback.from_user.full_name)
        await callback.answer("Готово")

    @dp.callback_query(F.data.startswith("ns_child:"))
    async def ns_child_switch(callback: CallbackQuery):
        user_id = callback.from_user.id
        user_data = get_netschool_user(user_id, callback.from_user.full_name)
        students = _get_available_students(user_data)
        if len(students) < 2:
            await callback.answer("У вас только один ребёнок в профиле", show_alert=True)
            return
        try:
            student_id = int((callback.data or "").split(":", 1)[1])
        except Exception:
            await callback.answer("Некорректный выбор", show_alert=True)
            return
        selected = next((item for item in students if item["id"] == student_id), None)
        if not selected:
            await callback.answer("Ребёнок не найден", show_alert=True)
            return
        if _safe_int(user_data.get("selected_student_id")) == student_id:
            await callback.message.answer(
                "ℹ️ Этот ребёнок уже выбран.",
                reply_markup=_build_student_switch_keyboard(user_data),
            )
            await callback.answer()
            return

        user_data["selected_student_id"] = student_id
        user_data["student_name"] = selected["name"]
        user_data["updated_at"] = datetime.now().isoformat()
        save_netschool_users()
        await refresh_user_grade_task(user_id, bot, runtime.log_bot, TG_ADMIN_ID)
        await callback.message.answer(
            f"✅ Активный ребёнок: <b>{html.escape(selected['name'])}</b>",
            parse_mode="HTML",
            reply_markup=_build_netschool_main_menu(user_data),
        )
        await callback.answer("Ребёнок переключён")

    @dp.message(Command("status"))
    async def ns_cmd_status(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        await message.answer(
            _build_status_text(user_data, user_id),
            parse_mode="HTML",
            reply_markup=_build_netschool_main_menu(user_data)
        )

    @dp.message(Command("profile"))
    async def ns_cmd_profile(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        await message.answer(_build_profile_text(user_data, user_id), parse_mode="HTML")

    @dp.message(Command("child", "children"))
    async def ns_cmd_child(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        user_data = get_netschool_user(user_id, message.from_user.full_name)
        await _show_child_switch_dialog(message, user_data)

    @dp.message(Command("mystats"))
    async def ns_cmd_mystats(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        status_msg = await message.answer("⌛ Считаю статистику...")
        ns = None
        try:
            quarter_start = _current_quarter_start()
            today_d = datetime.now(dt_timezone(timedelta(hours=3))).date()
            entries, ns = await _load_period_entries(message, user_id, quarter_start, today_d)
            user_data = get_netschool_user(user_id, message.from_user.full_name)
            await message.answer(
                _build_mystats_text(user_data, entries, student_name=get_user_student_name(user_id)),
                parse_mode="HTML"
            )
        finally:
            try:
                await status_msg.delete()
            except Exception:
                pass
            try:
                if ns and not getattr(ns, "_from_cache", False):
                    await _close_netschool_client(ns, do_logout=False)
            except Exception:
                pass

    @dp.message(Command("weeksummary"))
    async def ns_cmd_weeksummary(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        end_date = datetime.now(dt_timezone(timedelta(hours=3))).date()
        start_date = end_date - timedelta(days=6)
        status_msg = await message.answer("⌛ Готовлю недельную сводку...")
        ns = None
        try:
            entries, ns = await _load_period_entries(message, user_id, start_date, end_date)
            user_data = get_netschool_user(user_id, message.from_user.full_name)
            await message.answer(
                _build_weeksummary_text(user_data, entries, start_date, end_date),
                parse_mode="HTML"
            )
        finally:
            try:
                await status_msg.delete()
            except Exception:
                pass
            try:
                if ns and not getattr(ns, "_from_cache", False):
                    await _close_netschool_client(ns, do_logout=False)
            except Exception:
                pass

    @dp.message(Command("bugreport"))
    async def ns_cmd_bugreport(message: Message):
        """Отправка сообщения о баге администратору"""
        if message.chat.type != "private":
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            set_netschool_user_state(message.from_user.id, "await_bugreport")
            await message.answer(
                "🐛 Опишите проблему следующим сообщением.\n\n"
                "Можно написать свободным текстом. Для отмены нажмите кнопку ниже.",
                reply_markup=_kb_cancel_action()
            )
            return
        bug_text = parts[1].strip()
        if not bug_text or len(bug_text) < 5:
            await message.answer("❌ Описание бага слишком короткое. Пожалуйста, опишите проблему подробнее.")
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
            await message.answer("✅ Спасибо! Ваше сообщение о баге отправлено администратору.")
        except Exception as e:
            await message.answer("❌ Ошибка при отправке сообщения. Попробуйте позже.")
            print(f"Bug report error: {e}")

