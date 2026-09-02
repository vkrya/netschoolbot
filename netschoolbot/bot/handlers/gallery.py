"""Галерея PWA-иконок, доступ к мини-приложению, голосование за оценки."""

from ._common import *  # noqa: F401,F403
from ._common import *  # noqa: F401,F403


def register(dp: Dispatcher, bot: Bot) -> None:
    @dp.callback_query(F.data.startswith("ns_gradevote:"))
    async def ns_gradevote(callback: CallbackQuery):
        parts = (callback.data or "").split(":", 2)
        if len(parts) != 3:
            await callback.answer("Некорректный ответ", show_alert=True)
            return

        _, feedback_id, vote_value = parts
        if vote_value not in GRADE_FEEDBACK_LABELS:
            await callback.answer("Неизвестный вариант", show_alert=True)
            return

        store, entry = _ensure_grade_feedback_entry(feedback_id)
        votes = entry.setdefault("votes", {})
        user_key = str(callback.from_user.id)
        prev_value = votes.get(user_key)

        if prev_value == vote_value:
            await callback.answer(f"Уже выбрано: {GRADE_FEEDBACK_LABELS[vote_value]}")
            return

        votes[user_key] = vote_value
        entry["updated_at"] = datetime.now().isoformat()
        _save_grade_feedback_store(store)

        try:
            if callback.message:
                await callback.message.edit_reply_markup(
                    reply_markup=_build_grade_feedback_keyboard(feedback_id, store=store)
                )
        except Exception:
            pass

        if prev_value and prev_value in GRADE_FEEDBACK_LABELS:
            await callback.answer(
                f"Обновлено: {GRADE_FEEDBACK_LABELS[prev_value]} -> {GRADE_FEEDBACK_LABELS[vote_value]}"
            )
        else:
            await callback.answer(f"Ваш ответ: {GRADE_FEEDBACK_LABELS[vote_value]}")

    @dp.callback_query(F.data.startswith("ns_pwaacc:"))
    async def ns_pwa_access_request_action(callback: CallbackQuery):
        parts = (callback.data or "").split(":", 2)
        if len(parts) != 3:
            await callback.answer("Некорректный запрос", show_alert=True)
            return

        _, action, request_id = parts
        if action not in {"reject", "approve", "code"}:
            await callback.answer("Неизвестное действие", show_alert=True)
            return

        store = _load_netschool_miniapp_access_requests()
        _cleanup_expired_netschool_miniapp_access_requests(store)
        entry = store.setdefault("requests", {}).get(request_id)
        if not isinstance(entry, dict):
            _save_netschool_miniapp_access_requests(store)
            await callback.answer("Запрос уже истёк или не найден", show_alert=True)
            return

        owner_id = int(entry.get("user_id") or 0)
        if owner_id != callback.from_user.id:
            await callback.answer("Этот запрос предназначен другому пользователю", show_alert=True)
            return

        status = str(entry.get("status") or "pending")
        now_ts = int(time.time())
        expires_at = int(entry.get("expires_at") or 0)
        if status != "pending":
            await callback.answer(_format_netschool_pwa_access_status(status), show_alert=True)
            return
        if expires_at and expires_at < now_ts:
            entry["status"] = "expired"
            entry["resolved_at"] = now_ts
            _save_netschool_miniapp_access_requests(store)
            await callback.answer("Запрос истёк. Откройте недействительную ссылку снова, если нужно.", show_alert=True)
            return

        if action == "reject":
            entry["status"] = "rejected"
            entry["resolved_at"] = now_ts
            _save_netschool_miniapp_access_requests(store)
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await callback.message.answer("⛔ Вход по недействительной PWA-ссылке отклонён.")
            await callback.answer("Запрос отклонён")
            return

        code = _issue_netschool_session_code(owner_id)
        entry["status"] = "approved" if action == "approve" else "code_sent"
        entry["resolved_at"] = now_ts
        entry["code"] = code
        _save_netschool_miniapp_access_requests(store)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        prefix = "✅ Вход подтверждён." if action == "approve" else "🔐 Код отправлен без подтверждения входа."
        await bot.send_message(
            owner_id,
            f"{prefix}\n\n🔐 Код для входа в PWA: <b>{html.escape(code)}</b>\n\nДействует 5 минут. Не передавайте никому.",
            parse_mode="HTML",
        )
        await callback.answer("Код отправлен")

    @dp.message(Command("gallery"))
    async def ns_cmd_gallery(message: Message):
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        if user_id != TG_ADMIN_ID:
            await message.answer("Эта команда доступна только администратору.")
            return
        await _send_pwa_gallery_previews(message)

    @dp.callback_query(F.data.startswith("ns_gal_del:"))
    async def ns_gallery_delete(callback: CallbackQuery):
        user_id = callback.from_user.id
        if user_id != TG_ADMIN_ID:
            await callback.answer("Только для администратора", show_alert=True)
            return
        gallery_id = (callback.data or "").split(":", 1)[1]
        deleted, _ = _delete_pwa_gallery_icon(gallery_id)
        if not deleted:
            await callback.answer("Иконка не найдена", show_alert=True)
            return
        await callback.answer(f"Удалено: {gallery_id[:16]}", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass

    @dp.callback_query(F.data.startswith("ns_gal_revoke:"))
    async def ns_gallery_revoke(callback: CallbackQuery):
        user_id = callback.from_user.id
        if user_id != TG_ADMIN_ID:
            await callback.answer("Только для администратора", show_alert=True)
            return
        try:
            target_user_id = int((callback.data or "").split(":", 1)[1])
        except Exception:
            await callback.answer("Неверный user_id", show_alert=True)
            return
        revoked, icon_deleted = _revoke_pwa_icon_access(target_user_id)
        await callback.answer("Токены отозваны", show_alert=True)
        try:
            await callback.message.edit_caption(
                caption=(callback.message.caption or "") + f"\n\n⛔ Токены отозваны: {revoked}, иконка удалена: {'да' if icon_deleted else 'нет'}",
                reply_markup=None,
                parse_mode="HTML",
            )
        except Exception:
            pass

    @dp.callback_query(F.data == "ns_gal_close")
    async def ns_gallery_close(callback: CallbackQuery):
        await callback.message.delete()
        await callback.answer()

    @dp.message(Command("revoke_icon"))
    async def ns_cmd_revoke_icon(message: Message):
        """Revoke all tokens for a user by icon — forces them to change icon."""
        if message.chat.type != "private":
            return
        user_id = message.from_user.id
        if user_id != TG_ADMIN_ID:
            await message.answer("Эта команда доступна только администратору.")
            return
        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2:
            await _send_pwa_gallery_previews(message, mode="revoke")
            return
        try:
            target_user_id = int(args[1].strip())
        except ValueError:
            await message.answer("❌ user_id должен быть числом.")
            return
        # Revoke all tokens for this user
        store = _load_netschool_miniapp_tokens()
        tokens = store.get("tokens", {})
        revoked = 0
        to_remove = []
        for token_key, payload in tokens.items():
            if int(payload.get("user_id", 0)) == target_user_id:
                to_remove.append(token_key)
        for key in to_remove:
            del tokens[key]
            revoked += 1
        if revoked:
            _save_netschool_miniapp_tokens(store)
        # Also delete their custom icon
        icon_file = NETSCHOOL_USERS_DIR / "pwa_icons" / f"{target_user_id}.png"
        icon_deleted = False
        if icon_file.exists():
            icon_file.unlink()
            icon_deleted = True
        await message.answer(
            f"✅ Пользователь {target_user_id}:\n"
            f"• Отозвано токенов: {revoked}\n"
            f"• Иконка удалена: {'да' if icon_deleted else 'нет'}\n\n"
            "Для продолжения работы пользователь должен получить новый токен через бота."
        )

