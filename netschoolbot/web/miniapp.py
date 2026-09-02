"""Мини-приложение / PWA «Сетевой город»: страницы, API, push, кэш, галерея иконок."""

import asyncio
import base64
import html
import io
import json
import logging
import math
import mimetypes
import os
import re
import secrets
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from flask import (
    abort, jsonify, make_response, redirect, render_template_string, request,
    send_file, session, url_for,
)

from ..config import (
    MINIAPP_ACCESS_REQUEST_RESEND_COOLDOWN as NETSCHOOL_MINIAPP_ACCESS_REQUEST_RESEND_COOLDOWN,
    MINIAPP_ACCESS_REQUEST_TTL as NETSCHOOL_MINIAPP_ACCESS_REQUEST_TTL,
    MINIAPP_ACCESS_REQUESTS_FILE as NETSCHOOL_MINIAPP_ACCESS_REQUESTS_FILE,
    MINIAPP_ARCHIVE_TTL as NETSCHOOL_MINIAPP_ARCHIVE_TTL,
    MINIAPP_AUTOSAVE_INTERVAL_SECONDS as NETSCHOOL_MINIAPP_AUTOSAVE_INTERVAL_SECONDS,
    MINIAPP_CACHE_FRESH_SECONDS as NETSCHOOL_MINIAPP_CACHE_FRESH_SECONDS,
    MINIAPP_TOKENS_FILE as NETSCHOOL_MINIAPP_TOKENS_FILE,
    NETSCHOOL_CACHE_DIR,
    NETSCHOOL_MINIAPP_GALLERY_DIR,
    NETSCHOOL_MINIAPP_ICONS_DIR,
    NETSCHOOL_SESSIONS_DIR,
    NETSCHOOL_USERS_DIR,
    FEEDBACK_FILE as NETSCHOOL_FEEDBACK_FILE,
    GALLERY_INDEX_FILE as NETSCHOOL_GALLERY_INDEX_FILE,
    SESSION_CODES_FILE as NETSCHOOL_SESSION_CODES_FILE,
    USERS_FILE as NETSCHOOL_USERS_FILE,
    PROXY_REQUIRED_HOSTS,
    BOT_TOKEN as NETSCHOOL_BOT_TOKEN,
    ADMIN_ID as TG_ADMIN_ID,
    LOG_BOT_TOKEN,
)
from ..netschool.client import _make_netschool
from ..webpush import (
    push_summary,
    remove_user_subscription,
    send_user_push,
    upsert_user_subscription,
)
from .app import (
    STATIC_VERSION,
    _absolute_external_url_for,
    _check_auth,
    _external_url_for,
    _load_json_file,
    app,
)
from .templates import NETSCHOOL_MINIAPP_HTML

logger = logging.getLogger("netschoolbot.web")


def _normalize_miniapp_token_store(store: dict | None) -> dict:
  source = store if isinstance(store, dict) else {}
  tokens = source.get("tokens") if isinstance(source.get("tokens"), dict) else {}
  archived = source.get("archived_tokens") if isinstance(source.get("archived_tokens"), dict) else {}
  return {
    **source,
    "tokens": tokens,
    "archived_tokens": archived,
  }

def _archive_miniapp_token(store: dict, token: str, payload: dict | None, reason: str) -> None:
  if not token or not isinstance(payload, dict):
    return
  archived = store.setdefault("archived_tokens", {})
  archived[token] = {
    **payload,
    "archived_at": int(time.time()),
    "archive_reason": str(reason or "invalidated"),
  }

def _cleanup_expired_archived_miniapp_tokens(store: dict) -> bool:
  archived = store.setdefault("archived_tokens", {})
  now_ts = int(time.time())
  expired = [
    key for key, payload in archived.items()
    if int((payload or {}).get("archived_at", 0)) + NETSCHOOL_MINIAPP_ARCHIVE_TTL <= now_ts
  ]
  for key in expired:
    archived.pop(key, None)
  return bool(expired)

def _cleanup_expired_miniapp_tokens(store: dict) -> bool:
  normalized = _normalize_miniapp_token_store(store)
  store.clear()
  store.update(normalized)
  tokens = store.setdefault("tokens", {})
  now_ts = int(time.time())
  expired = [key for key, payload in tokens.items() if int((payload or {}).get("expires_at", 0)) <= now_ts]
  for key in expired:
    payload = tokens.pop(key, None)
    _archive_miniapp_token(store, key, payload, "expired")
  archived_changed = _cleanup_expired_archived_miniapp_tokens(store)
  return bool(expired) or archived_changed

def _save_miniapp_tokens(store: dict) -> None:
  NETSCHOOL_MINIAPP_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
  normalized = _normalize_miniapp_token_store(store)
  NETSCHOOL_MINIAPP_TOKENS_FILE.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
  os.chmod(NETSCHOOL_MINIAPP_TOKENS_FILE, 0o600)

def _consume_netschool_miniapp_token(token: str) -> str | None:
  if not token:
    return None
  store = _normalize_miniapp_token_store(_load_json_file(NETSCHOOL_MINIAPP_TOKENS_FILE, {"tokens": {}}))
  changed = _cleanup_expired_miniapp_tokens(store)
  payload = store.get("tokens", {}).pop(token, None)
  if isinstance(payload, dict):
    _archive_miniapp_token(store, token, payload, "consumed")
  if changed or payload is not None:
    _save_miniapp_tokens(store)
  if not isinstance(payload, dict):
    return None
  try:
    return str(int(payload.get("user_id")))
  except Exception:
    return None

def _validate_netschool_miniapp_token(token: str) -> str | None:
  """Validate without consuming — for reusable PWA tokens."""
  if not token:
    return None
  store = _normalize_miniapp_token_store(_load_json_file(NETSCHOOL_MINIAPP_TOKENS_FILE, {"tokens": {}}))
  changed = _cleanup_expired_miniapp_tokens(store)
  payload = store.get("tokens", {}).get(token)
  if changed:
    _save_miniapp_tokens(store)
  if not isinstance(payload, dict):
    return None
  try:
    return str(int(payload.get("user_id")))
  except Exception:
    return None

def _resolve_netschool_miniapp_token_owner(token: str) -> int | None:
  if not token:
    return None
  store = _normalize_miniapp_token_store(_load_json_file(NETSCHOOL_MINIAPP_TOKENS_FILE, {"tokens": {}}))
  changed = _cleanup_expired_miniapp_tokens(store)
  payload = store.get("tokens", {}).get(token) or store.get("archived_tokens", {}).get(token)
  if changed:
    _save_miniapp_tokens(store)
  if not isinstance(payload, dict):
    return None
  try:
    user_id = int(payload.get("user_id") or 0)
  except Exception:
    return None
  return user_id or None

def _find_existing_netschool_miniapp_token(user_id: str | int | None) -> str:
  try:
    user_key = str(int(user_id))
  except Exception:
    return ""
  store = _normalize_miniapp_token_store(_load_json_file(NETSCHOOL_MINIAPP_TOKENS_FILE, {"tokens": {}}))
  changed = _cleanup_expired_miniapp_tokens(store)
  best_token = ""
  best_expiry = 0
  for token, payload in (store.get("tokens", {}) or {}).items():
    if str((payload or {}).get("user_id") or "") != user_key:
      continue
    expires_at = int((payload or {}).get("expires_at") or 0)
    if expires_at >= best_expiry:
      best_token = str(token)
      best_expiry = expires_at
  if changed:
    _save_miniapp_tokens(store)
  return best_token

def _extract_netschool_miniapp_token() -> str:
  query_token = request.args.get("token", "").strip()
  if query_token:
    return query_token
  header_token = request.headers.get("X-Netschool-Miniapp-Token", "").strip()
  if header_token:
    return header_token
  return ""

def _restore_netschool_miniapp_session_from_token(token: str) -> str | None:
  user_id = _validate_netschool_miniapp_token(token)
  if not user_id:
    return None
  session.permanent = True
  session["netschool_miniapp_user_id"] = user_id
  session["netschool_miniapp_token"] = token
  return user_id

@app.before_request
def _ensure_netschool_miniapp_session():
  path = request.path or ""
  if not (path.startswith("/mini/netschool") or path.startswith("/api/mini/netschool")):
    return
  if session.get("netschool_miniapp_user_id"):
    token = _extract_netschool_miniapp_token()
    if token:
      token_user_id = _validate_netschool_miniapp_token(token)
      current_user_id = str(session.get("netschool_miniapp_user_id") or "")
      if token_user_id and token_user_id != current_user_id:
        session.pop("netschool_miniapp_user_id", None)
        session.pop("netschool_miniapp_token", None)
        if path.startswith("/api/mini/netschool"):
          return jsonify({"error": "Ссылка mini app устарела. Откройте новую ссылку или войдите через код из Telegram."}), 401
        return redirect(_external_url_for("netschool_miniapp_page"))
      if token_user_id == current_user_id:
        session["netschool_miniapp_token"] = token
    return
  token = _extract_netschool_miniapp_token()
  if token:
    _restore_netschool_miniapp_session_from_token(token)

def _get_netschool_user_by_id(user_id: str | int | None) -> dict | None:
  if user_id in (None, ""):
    return None
  try:
    user_key = str(int(user_id))
  except Exception:
    return None
  users_payload = _load_json_file(NETSCHOOL_USERS_FILE, {"users": {}})
  users = users_payload.get("users", {}) if isinstance(users_payload, dict) else {}
  user_data = users.get(user_key)
  if not isinstance(user_data, dict):
    return None
  user_data = dict(user_data)
  user_data.setdefault("user_id", int(user_key))
  return user_data

def _get_netschool_miniapp_user() -> dict | None:
  return _get_netschool_user_by_id(session.get("netschool_miniapp_user_id"))

def _get_current_netschool_miniapp_token() -> str:
  fallback = _find_existing_netschool_miniapp_token(session.get("netschool_miniapp_user_id"))
  if fallback:
    session["netschool_miniapp_token"] = fallback
    return fallback
  token = str(session.get("netschool_miniapp_token") or "").strip()
  if token and _validate_netschool_miniapp_token(token):
    return token
  return ""

def _sanitize_pwa_icon_emoji(value: str | None) -> str:
  cleaned = str(value or "").strip()
  return cleaned[:2] if cleaned else "📘"

def _sanitize_pwa_icon_bg(value: str | None) -> str:
  cleaned = str(value or "").strip()
  return cleaned if re.fullmatch(r"#[0-9a-fA-F]{6}", cleaned) else "#4a76a8"

def _get_pwa_icon_version(source: dict | None) -> str:
  value = str((source or {}).get("pwa_icon_version") or "").strip()
  return value or "0"

def _netschool_miniapp_icon_file(user_id: int | str | None) -> Path:
  return NETSCHOOL_MINIAPP_ICONS_DIR / f"{int(user_id or 0)}.png"

def _has_netschool_custom_icon(user_id: int | str | None) -> bool:
  try:
    return _netschool_miniapp_icon_file(user_id).exists()
  except Exception:
    return False

def _delete_netschool_custom_icon(user_id: int | str | None) -> None:
  icon_file = _netschool_miniapp_icon_file(user_id)
  if icon_file.exists():
    icon_file.unlink()

def _store_netschool_custom_icon(user_id: int | str, image_data: str) -> None:
  payload = str(image_data or "").strip()
  if not payload.startswith("data:image/") or "," not in payload:
    raise ValueError("Загрузите изображение через форму mini app.")
  _, encoded = payload.split(",", 1)
  try:
    binary = base64.b64decode(encoded, validate=True)
  except Exception as exc:
    raise ValueError("Не удалось обработать картинку.") from exc
  if not binary:
    raise ValueError("Файл с картинкой пустой.")
  if len(binary) > 2_500_000:
    raise ValueError("Картинка слишком большая после обработки.")
  NETSCHOOL_MINIAPP_ICONS_DIR.mkdir(parents=True, exist_ok=True)
  icon_file = _netschool_miniapp_icon_file(user_id)
  icon_file.write_bytes(binary)
  os.chmod(icon_file, 0o600)

# ── Session recovery codes ────────────────────────────────────
def _load_session_codes() -> dict:
  return _load_json_file(NETSCHOOL_SESSION_CODES_FILE, {"codes": {}})

def _save_session_codes(store: dict) -> None:
  NETSCHOOL_SESSION_CODES_FILE.parent.mkdir(parents=True, exist_ok=True)
  NETSCHOOL_SESSION_CODES_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
  os.chmod(NETSCHOOL_SESSION_CODES_FILE, 0o600)

def _cleanup_expired_session_codes(store: dict) -> None:
  now = int(time.time())
  codes = store.get("codes", {})
  expired = [k for k, v in codes.items() if int(v.get("expires_at") or 0) < now]
  for k in expired:
    del codes[k]

def _issue_session_code(user_id: int) -> str:
  store = _load_session_codes()
  _cleanup_expired_session_codes(store)
  codes = store.setdefault("codes", {})
  # Remove existing codes for this user
  old = [k for k, v in codes.items() if int(v.get("user_id") or 0) == user_id]
  for k in old:
    del codes[k]
  code = str(secrets.randbelow(900000) + 100000)  # 6-digit
  codes[code] = {"user_id": user_id, "expires_at": int(time.time()) + 300}  # 5 minutes
  _save_session_codes(store)
  return code

def _verify_session_code(code: str) -> int | None:
  store = _load_session_codes()
  _cleanup_expired_session_codes(store)
  entry = store.get("codes", {}).get(str(code))
  if not entry:
    return None
  user_id = int(entry.get("user_id") or 0)
  # Consume the code
  del store["codes"][str(code)]
  _save_session_codes(store)
  return user_id if user_id else None

def _load_miniapp_access_requests() -> dict:
  data = _load_json_file(NETSCHOOL_MINIAPP_ACCESS_REQUESTS_FILE, {"requests": {}})
  requests_store = data.get("requests") if isinstance(data, dict) and isinstance(data.get("requests"), dict) else {}
  return {"requests": requests_store}

def _save_miniapp_access_requests(store: dict) -> None:
  NETSCHOOL_MINIAPP_ACCESS_REQUESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
  NETSCHOOL_MINIAPP_ACCESS_REQUESTS_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
  os.chmod(NETSCHOOL_MINIAPP_ACCESS_REQUESTS_FILE, 0o600)

def _cleanup_expired_miniapp_access_requests(store: dict) -> bool:
  requests_store = store.setdefault("requests", {})
  now_ts = int(time.time())
  removed = []
  for request_id, entry in list(requests_store.items()):
    if not isinstance(entry, dict):
      removed.append(request_id)
      continue
    expires_at = int(entry.get("expires_at") or 0)
    created_at = int(entry.get("created_at") or 0)
    status = str(entry.get("status") or "pending")
    if expires_at and expires_at < now_ts and status == "pending":
      entry["status"] = "expired"
      entry["resolved_at"] = now_ts
    if status in {"rejected", "approved", "code_sent", "expired"} and created_at and created_at + 86400 < now_ts:
      removed.append(request_id)
  for request_id in removed:
    requests_store.pop(request_id, None)
  return bool(removed)

def _create_or_reuse_miniapp_access_request(token: str, user_id: int) -> tuple[dict, bool]:
  now_ts = int(time.time())
  store = _load_miniapp_access_requests()
  changed = _cleanup_expired_miniapp_access_requests(store)
  requests_store = store.setdefault("requests", {})
  for request_id, entry in requests_store.items():
    if not isinstance(entry, dict):
      continue
    if str(entry.get("token") or "") != token:
      continue
    if int(entry.get("user_id") or 0) != int(user_id):
      continue
    if str(entry.get("status") or "") != "pending":
      continue
    last_sent_at = int(entry.get("last_sent_at") or entry.get("created_at") or 0)
    should_send = now_ts - last_sent_at >= NETSCHOOL_MINIAPP_ACCESS_REQUEST_RESEND_COOLDOWN
    if should_send:
      entry["last_sent_at"] = now_ts
      changed = True
    if changed:
      _save_miniapp_access_requests(store)
    return dict(entry, request_id=request_id), should_send

  request_id = secrets.token_hex(8)
  entry = {
    "token": token,
    "user_id": int(user_id),
    "status": "pending",
    "created_at": now_ts,
    "expires_at": now_ts + NETSCHOOL_MINIAPP_ACCESS_REQUEST_TTL,
    "last_sent_at": now_ts,
    "requested_at": datetime.now().isoformat(),
    "remote_addr": str(request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:200],
    "user_agent": str(request.headers.get("User-Agent") or "")[:500],
  }
  requests_store[request_id] = entry
  _save_miniapp_access_requests(store)
  return dict(entry, request_id=request_id), True

def _send_miniapp_access_request_to_telegram(user_id: int, request_entry: dict) -> bool:
  bot_token = (
    os.getenv("NETSCHOOL_BOT_TOKEN")
    or os.getenv("TG_BOT_TOKEN")
    or os.getenv("BOT_TOKEN")
    or ""
  )
  request_id = str(request_entry.get("request_id") or "").strip()
  if not bot_token or not request_id:
    return False
  remote_addr = html.escape(str(request_entry.get("remote_addr") or "—"))
  user_agent = html.escape(str(request_entry.get("user_agent") or "")[:180] or "—")
  text = (
    "⚠️ Кто-то открыл недействительную PWA-ссылку NetSchool.\n\n"
    "Если это вы, выберите действие ниже. При подтверждении или выборе «просто код» я отправлю код входа в этот чат.\n\n"
    f"IP: <code>{remote_addr}</code>\n"
    f"Устройство: <code>{user_agent}</code>"
  )
  payload_data = json.dumps({
    "chat_id": int(user_id),
    "text": text,
    "parse_mode": "HTML",
    "reply_markup": {
      "inline_keyboard": [
        [{"text": "⛔ Отклонить вход", "callback_data": f"ns_pwaacc:reject:{request_id}"}],
        [{"text": "✅ Подтвердить вход", "callback_data": f"ns_pwaacc:approve:{request_id}"}],
        [{"text": "🔐 Просто прислать код", "callback_data": f"ns_pwaacc:code:{request_id}"}],
      ]
    }
  }).encode("utf-8")
  req = urllib.request.Request(
    f"https://api.telegram.org/bot{bot_token}/sendMessage",
    data=payload_data,
    headers={"Content-Type": "application/json"},
  )
  try:
    urllib.request.urlopen(req, timeout=10)
    return True
  except Exception:
    return False

def _request_invalid_token_recovery(token: str) -> bool:
  owner_id = _resolve_netschool_miniapp_token_owner(token)
  if not owner_id:
    return False
  request_entry, should_send = _create_or_reuse_miniapp_access_request(token, owner_id)
  if not should_send:
    return True
  sent = _send_miniapp_access_request_to_telegram(owner_id, request_entry)
  if sent:
    return True
  request_id = str(request_entry.get("request_id") or "").strip()
  if request_id:
    store = _load_miniapp_access_requests()
    entry = store.setdefault("requests", {}).get(request_id)
    if isinstance(entry, dict):
      entry["last_sent_at"] = 0
      _save_miniapp_access_requests(store)
  return False

def _get_netschool_miniapp_user_for_request() -> dict | None:
  user_data = _get_netschool_miniapp_user()
  if user_data:
    return user_data
  token = str(request.args.get("token") or "").strip()
  if not token:
    return None
  user_id = _validate_netschool_miniapp_token(token)
  return _get_netschool_user_by_id(int(user_id)) if user_id else None

# ── Icon gallery ──────────────────────────────────────────────

def _load_gallery_index() -> list:
  data = _load_json_file(NETSCHOOL_GALLERY_INDEX_FILE, {"icons": []})
  return data.get("icons", [])

def _save_gallery_index(icons: list) -> None:
  NETSCHOOL_GALLERY_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
  NETSCHOOL_GALLERY_INDEX_FILE.write_text(json.dumps({"icons": icons}, ensure_ascii=False, indent=2), encoding="utf-8")

def _get_gallery_icon_owner(gallery_id: str) -> int | None:
  for icon in _load_gallery_index():
    if str(icon.get("id") or "") == gallery_id:
      try:
        return int(icon.get("user_id") or 0)
      except Exception:
        return None
  return None

def _add_icon_to_gallery(user_id: int) -> None:
  """Copy user's icon to gallery if it exists and mark it public."""
  src = _netschool_miniapp_icon_file(user_id)
  if not src.exists():
    return
  NETSCHOOL_MINIAPP_GALLERY_DIR.mkdir(parents=True, exist_ok=True)
  gallery_id = f"{user_id}_{int(time.time())}"
  dst = NETSCHOOL_MINIAPP_GALLERY_DIR / f"{gallery_id}.png"
  import shutil
  shutil.copy2(str(src), str(dst))
  icons = _load_gallery_index()
  icons.append({
    "id": gallery_id,
    "user_id": user_id,
    "created_at": datetime.now().isoformat(),
  })
  _save_gallery_index(icons)

def _remove_gallery_icon(gallery_id: str) -> bool:
  icons = _load_gallery_index()
  found = False
  new_icons = []
  for icon in icons:
    if icon.get("id") == gallery_id:
      found = True
      gfile = NETSCHOOL_MINIAPP_GALLERY_DIR / f"{gallery_id}.png"
      if gfile.exists():
        gfile.unlink()
    else:
      new_icons.append(icon)
  if found:
    _save_gallery_index(new_icons)
  return found

def _list_gallery_icons() -> list:
  icons = _load_gallery_index()
  result = []
  for icon in icons:
    gfile = NETSCHOOL_MINIAPP_GALLERY_DIR / f"{icon['id']}.png"
    if gfile.exists():
      result.append(icon)
  return result

def _with_token_and_version(url: str, source: dict | None = None) -> str:
  params = []
  token = _get_current_netschool_miniapp_token() or str(request.args.get("token") or "").strip()
  if token:
    params.append(f"token={quote(token)}")
  version = _get_pwa_icon_version(source)
  if version != "0":
    params.append(f"v={quote(version)}")
  if not params:
    return url
  return f"{url}{'&' if '?' in url else '?'}{'&'.join(params)}"

def _netschool_miniapp_icon_url(source: dict | None = None) -> str:
  return _with_token_and_version(_absolute_external_url_for("netschool_miniapp_icon"), source)

def _netschool_miniapp_manifest_url(source: dict | None = None) -> str:
  return _with_token_and_version(_absolute_external_url_for("netschool_miniapp_manifest"), source)

def _issue_netschool_pwa_link(user_id: int, *, revoke_existing: bool = False) -> str:
  if not revoke_existing:
    existing = _find_existing_netschool_miniapp_token(user_id)
    if existing:
      return f"{_absolute_external_url_for('netschool_miniapp_page')}?token={existing}"
  store = _normalize_miniapp_token_store(_load_json_file(NETSCHOOL_MINIAPP_TOKENS_FILE, {"tokens": {}}))
  _cleanup_expired_miniapp_tokens(store)
  tokens = store.setdefault("tokens", {})
  if revoke_existing:
    old_keys = [key for key, value in tokens.items() if value.get("user_id") == int(user_id)]
    for key in old_keys:
      payload = tokens.pop(key, None)
      _archive_miniapp_token(store, key, payload, "revoked")
  token = secrets.token_urlsafe(24)
  tokens[token] = {
    "user_id": int(user_id),
    "issued_at": int(time.time()),
    "expires_at": int(time.time()) + 86400 * 365,
  }
  _save_miniapp_tokens(store)
  return f"{_absolute_external_url_for('netschool_miniapp_page')}?token={token}"

def _render_netschool_miniapp_response(*, error: str | None = None, data: dict | None = None):
  cached_dash = None
  user_id = session.get("netschool_miniapp_user_id")
  try:
    if user_id:
      cached_dash = _load_netschool_miniapp_cache_section(int(user_id), "dashboard")
  except Exception:
    cached_dash = None
  response = make_response(render_template_string(
    NETSCHOOL_MINIAPP_HTML,
    error=error,
    data=data,
    manifest_url=_netschool_miniapp_manifest_url(data),
    page_url=_external_url_for("netschool_miniapp_page"),
    icon_url=_netschool_miniapp_icon_url(data),
    initial_dash=cached_dash,
    initial_mail=None,
  ))
  response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
  response.headers["Pragma"] = "no-cache"
  response.headers["Referrer-Policy"] = "same-origin"
  response.headers["X-Frame-Options"] = "SAMEORIGIN"
  return response

def _status_meta(enabled: bool, on_text: str = "Включено", off_text: str = "Выключено") -> tuple[str, str]:
  return (on_text, "ok") if enabled else (off_text, "off")

def _build_netschool_miniapp_payload(user_data: dict) -> dict:
  user_id = int(user_data.get("user_id") or 0)
  def _is_generic_student_name(value: str) -> bool:
    return bool(re.match(r"^(ученик|учаник|student)\s+\d+$", str(value or "").strip(), flags=re.IGNORECASE))

  student_name = str(user_data.get("student_name") or "").strip()
  school = user_data.get("netschool_school") or "Не указана"
  netschool_url = user_data.get("netschool_url") or "Не указан"
  subject_filters = ", ".join(user_data.get("subject_filters", {}).get("include") or []) or "Все предметы"
  type_filters = ", ".join(user_data.get("filters", {}).get("exclude") or []) or "Нет"
  quiet_hours = user_data.get("quiet_hours", {}) or {}
  quiet_label = "Отключены"
  if quiet_hours.get("start") and quiet_hours.get("end"):
    quiet_label = f"{quiet_hours.get('start')} - {quiet_hours.get('end')}"
  enabled_label, enabled_class = _status_meta(bool(user_data.get("enabled")), "Активно", "Пауза")
  mail_label, mail_class = _status_meta(bool(user_data.get("notify_mail", True)))
  changes_label, changes_class = _status_meta(bool(user_data.get("notify_changes", True)))
  deletes_label, deletes_class = _status_meta(bool(user_data.get("notify_deletes", True)))
  weekly_label, weekly_class = _status_meta(bool(user_data.get("weekly_summary_enabled")))
  homework_label, homework_class = _status_meta(bool(user_data.get("notify_homework", True)))
  push_mode = str(user_data.get("push_mode") or "both")
  push_mode_label = {
    "telegram": "Только Telegram",
    "app": "Только приложение",
    "both": "Приложение и Telegram",
  }.get(push_mode, "Только Telegram")
  push_info = push_summary(user_id) if user_id else {"configured": False, "count": 0, "public_key": ""}
  if not push_info.get("configured"):
    push_status_label = "Сервер push не настроен"
  elif push_info.get("count"):
    push_status_label = f"Подключено устройств: {push_info.get('count')}"
  else:
    push_status_label = "Подписка появится автоматически после установки PWA"
  interval_minutes = max(1, int((user_data.get("check_interval") or 300)) // 60)
  available_students = []
  for item in user_data.get("available_students") or []:
    if not isinstance(item, dict):
      continue
    try:
      sid = int(item.get("id"))
    except Exception:
      continue
    name = str(item.get("name") or "").strip() or f"Ученик {sid}"
    available_students.append({"id": sid, "name": name})
  selected_student_id = user_data.get("selected_student_id")
  try:
    selected_student_id = int(selected_student_id) if selected_student_id is not None else None
  except Exception:
    selected_student_id = None
  if not student_name or _is_generic_student_name(student_name):
    selected_student = next((item for item in available_students if selected_student_id is not None and item.get("id") == selected_student_id), None)
    selected_name = str((selected_student or {}).get("name") or "").strip()
    if selected_name and not _is_generic_student_name(selected_name):
      student_name = selected_name
    elif user_data.get("display_name"):
      student_name = str(user_data.get("display_name") or "").strip()
    elif selected_name:
      student_name = selected_name
    else:
      student_name = "Пользователь NetSchool"
  return {
    "student_name": student_name,
    "display_name": user_data.get("display_name") or "Не указан",
    "school": school,
    "login": user_data.get("login") or "Не указан",
    "netschool_url": netschool_url,
    "login_type": user_data.get("login_type") or "password",
    "enabled_label": enabled_label,
    "enabled_class": enabled_class,
    "mail_label": mail_label,
    "mail_class": mail_class,
    "mail_unread_count": max(0, int(user_data.get("mail_unread_count") or 0)),
    "changes_label": changes_label,
    "changes_class": changes_class,
    "deletes_label": deletes_label,
    "deletes_class": deletes_class,
    "weekly_label": weekly_label,
    "weekly_class": weekly_class,
    "homework_label": homework_label,
    "homework_class": homework_class,
    "push_mode": push_mode,
    "push_mode_label": push_mode_label,
    "push_status_label": push_status_label,
    "push_subscription_count": push_info.get("count", 0),
    "push_configured": bool(push_info.get("configured")),
    "push_public_key": push_info.get("public_key") or "",
    "miniapp_token": _get_current_netschool_miniapp_token(),
    "pwa_icon_emoji": _sanitize_pwa_icon_emoji(user_data.get("pwa_icon_emoji")),
    "pwa_icon_bg": _sanitize_pwa_icon_bg(user_data.get("pwa_icon_bg")),
    "pwa_icon_has_image": _has_netschool_custom_icon(user_id),
    "pwa_icon_url": _netschool_miniapp_icon_url(user_data),
    "pwa_icon_version": _get_pwa_icon_version(user_data),
    "quiet_hours": quiet_label,
    "subject_filters": subject_filters,
    "type_filters": type_filters,
    "interval_label": f"{interval_minutes} мин",
    "last_sync_at": user_data.get("last_sync_at") or "Еще не было",
    "theme": str(user_data.get("miniapp_theme") or "light"),
    "theme_saved": "miniapp_theme" in user_data,
    "theme_updated_at": str(user_data.get("miniapp_theme_updated_at") or ""),
    "accent_color": str(user_data.get("miniapp_accent_color") or ""),
    "accent_saved": "miniapp_accent_color" in user_data,
    "accent_updated_at": str(user_data.get("miniapp_accent_color_updated_at") or ""),
    "theme_sync": bool(user_data.get("miniapp_theme_sync", True)),
    "available_students": available_students,
    "selected_student_id": selected_student_id,
  }

def _build_netschool_appearance_payload(user_data: dict) -> dict:
  profile = _build_netschool_miniapp_payload(user_data)
  return {
    "theme": profile.get("theme") or "light",
    "theme_saved": bool(profile.get("theme_saved")),
    "theme_updated_at": profile.get("theme_updated_at") or "",
    "accent_color": profile.get("accent_color") or "",
    "accent_saved": bool(profile.get("accent_saved")),
    "accent_updated_at": profile.get("accent_updated_at") or "",
    "theme_sync": profile.get("theme_sync") is not False,
  }

def _save_netschool_user_data(user_id: int, user_data: dict) -> None:
  payload = _load_json_file(NETSCHOOL_USERS_FILE, {"users": {}})
  users = payload.setdefault("users", {})
  users[str(user_id)] = user_data
  NETSCHOOL_USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
  NETSCHOOL_USERS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def _normalize_mail_seen_ids(values, *, limit: int = 500) -> list[int]:
  normalized: set[int] = set()
  for value in values or []:
    try:
      normalized.add(int(value))
    except Exception:
      continue
  return sorted(normalized, reverse=True)[:max(1, limit)]

async def _prime_netschool_mail_client(client) -> None:
  await client.mail_list(folder="Inbox", page=1, page_size=1)

def _netschool_cache_path(user_id: int) -> Path:
  return NETSCHOOL_CACHE_DIR / f"cache_{user_id}.json"

def _load_netschool_cache(user_id: int) -> dict:
  return _load_json_file(_netschool_cache_path(user_id), {})

def _save_netschool_cache(user_id: int, data: dict) -> None:
  path = _netschool_cache_path(user_id)
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_netschool_miniapp_cache_section(user_id: int, section: str):
  cache = _load_netschool_cache(user_id)
  return ((cache.get("miniapp") or {}).get(section) or {}).get("payload")

def _load_netschool_miniapp_cache_entry(user_id: int, section: str) -> dict | None:
  cache = _load_netschool_cache(user_id)
  section_data = (cache.get("miniapp") or {}).get(section)
  if isinstance(section_data, dict):
    return section_data
  return None

def _save_netschool_miniapp_cache_section(user_id: int, section: str, payload: dict) -> None:
  cache = _load_netschool_cache(user_id)
  miniapp_cache = cache.setdefault("miniapp", {})
  miniapp_cache[section] = {
    "updated_at": datetime.now().isoformat(),
    "payload": payload,
  }
  _save_netschool_cache(user_id, cache)

def _parse_iso_datetime(value) -> datetime | None:
  if not value:
    return None
  try:
    raw = str(value).strip()
    if raw.endswith("Z"):
      raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)
  except Exception:
    return None

def _is_cache_entry_fresh(entry: dict | None, max_age_seconds: int = NETSCHOOL_MINIAPP_CACHE_FRESH_SECONDS) -> bool:
  if not isinstance(entry, dict):
    return False
  updated = _parse_iso_datetime(entry.get("updated_at"))
  if updated is None:
    return False
  return (datetime.now() - updated).total_seconds() <= max_age_seconds

def _append_netschool_feedback(entry: dict) -> None:
  NETSCHOOL_FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
  with NETSCHOOL_FEEDBACK_FILE.open("a", encoding="utf-8") as fp:
    fp.write(json.dumps(entry, ensure_ascii=False) + "\n")

def _send_netschool_feedback_to_telegram(entry: dict) -> bool:
  bot_token = str(os.getenv("LOG_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN") or os.getenv("NETSCHOOL_BOT_TOKEN") or "").strip()
  admin_chat_id_raw = str(os.getenv("TG_ADMIN_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
  if not bot_token or not admin_chat_id_raw:
    return False
  try:
    chat_id = int(admin_chat_id_raw)
  except Exception:
    return False
  user_payload = entry.get("user") or {}
  logs_block = {
    "tab": entry.get("current_tab") or "",
    "page_url": entry.get("page_url") or "",
    "standalone": bool(entry.get("standalone")),
    "remote_addr": entry.get("remote_addr") or "",
    "user_agent": entry.get("user_agent") or "",
    "created_at": entry.get("created_at") or "",
  }
  logs_json = json.dumps(logs_block, ensure_ascii=False, indent=2)
  text = "\n".join([
    "NetSchool mini app feedback",
    f"Тип: {'Идея' if entry.get('kind') == 'feature' else 'Баг'}",
    f"Тема: {entry.get('subject') or 'Без темы'}",
    f"Раздел: {entry.get('current_tab') or '—'}",
    f"Ученик: {user_payload.get('student_name') or '—'}",
    f"Логин: {user_payload.get('login') or '—'}",
    f"User ID: {user_payload.get('id') or '—'}",
    "",
    str(entry.get('message') or ''),
    "",
    "Логи:",
    logs_json,
  ]).strip()
  payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
  req = urllib.request.Request(
    f"https://api.telegram.org/bot{bot_token}/sendMessage",
    data=payload,
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST",
  )
  try:
    with urllib.request.urlopen(req, timeout=10) as response:
      return 200 <= getattr(response, "status", 0) < 300
  except Exception:
    return False

def _academic_year_start(today: date | None = None) -> date:
  current = today or datetime.now(timezone(timedelta(hours=3))).date()
  return datetime(current.year if current.month >= 9 else current.year - 1, 9, 1).date()

def _quarter_ranges(today: date | None = None) -> list[tuple[str, str, date, date]]:
  start = _academic_year_start(today)
  year = start.year
  return [
    ("q1", "1 четверть", datetime(year, 9, 1).date(), datetime(year, 10, 31).date()),
    ("q2", "2 четверть", datetime(year, 11, 1).date(), datetime(year, 12, 31).date()),
    ("q3", "3 четверть", datetime(year + 1, 1, 9).date(), datetime(year + 1, 3, 31).date()),
    ("q4", "4 четверть", datetime(year + 1, 4, 1).date(), datetime(year + 1, 8, 31).date()),
  ]

def _quarter_key_for_date(target_date: date, today: date | None = None) -> str | None:
  for key, _label, start, end in _quarter_ranges(today):
    if start <= target_date <= end:
      return key
  return None

def _current_quarter_label(today: date | None = None) -> str:
  current = today or datetime.now(timezone(timedelta(hours=3))).date()
  for _key, label, start, end in _quarter_ranges(current):
    if start <= current <= end:
      return label
  return "Текущий период"

def _toggle_netschool_setting(user_id: int, key: str, value: str | None = None) -> tuple[dict, str]:
  user_data = _get_netschool_user_by_id(user_id)
  if not user_data:
    raise RuntimeError("Профиль NetSchool не найден.")

  if key == "theme":
    theme = str(value or "light").strip().lower()
    if theme not in ("light", "dark"):
      theme = "light"
    user_data["miniapp_theme"] = theme
    user_data["miniapp_theme_updated_at"] = datetime.now().isoformat()
    user_data["updated_at"] = datetime.now().isoformat()
    _save_netschool_user_data(int(user_id), user_data)
    return user_data, f"Тема: {theme}"

  if key == "accent_color":
    color = str(value or "").strip()
    if color and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
      user_data["miniapp_accent_color"] = color
    else:
      user_data.pop("miniapp_accent_color", None)
    user_data["miniapp_accent_color_updated_at"] = datetime.now().isoformat()
    user_data["updated_at"] = datetime.now().isoformat()
    _save_netschool_user_data(int(user_id), user_data)
    return user_data, "Цвет обновлён"

  if key == "theme_sync":
    enabled = str(value or "true").strip().lower() in {"1", "true", "yes", "on"}
    user_data["miniapp_theme_sync"] = enabled
    user_data["updated_at"] = datetime.now().isoformat()
    _save_netschool_user_data(int(user_id), user_data)
    return user_data, "Синхронизация оформления включена" if enabled else "Синхронизация оформления отключена"

  if key == "push_mode":
    modes = ["telegram", "app", "both"]
    next_mode = str(value or "").strip().lower()
    if next_mode not in modes:
      current = str(user_data.get("push_mode") or "telegram")
      try:
        next_mode = modes[(modes.index(current) + 1) % len(modes)]
      except ValueError:
        next_mode = "telegram"
    user_data["push_mode"] = next_mode
    user_data["updated_at"] = datetime.now().isoformat()
    _save_netschool_user_data(int(user_id), user_data)
    label = {
      "telegram": "только Telegram",
      "app": "только приложение",
      "both": "приложение и Telegram",
    }[next_mode]
    return user_data, f"Канал уведомлений: {label}"

  key_map = {
    "enabled": "enabled",
    "mail": "notify_mail",
    "changes": "notify_changes",
    "deletes": "notify_deletes",
    "weekly": "weekly_summary_enabled",
    "homework": "notify_homework",
  }
  defaults = {
    "enabled": False,
    "notify_mail": True,
    "notify_changes": True,
    "notify_deletes": True,
    "weekly_summary_enabled": False,
    "notify_homework": True,
  }
  if key not in key_map:
    raise RuntimeError("Неизвестная настройка.")

  field = key_map[key]
  user_data[field] = not bool(user_data.get(field, defaults[field]))
  user_data["updated_at"] = datetime.now().isoformat()
  _save_netschool_user_data(int(user_id), user_data)

  labels = {
    "enabled": "Уведомления об оценках",
    "mail": "Почта",
    "changes": "Изменения оценок",
    "deletes": "Удаления оценок",
    "weekly": "Недельная сводка",
    "homework": "Домашние задания",
  }
  state_label = "включено" if bool(user_data.get(field)) else "выключено"
  return user_data, f"{labels[key]}: {state_label}"

def _netschool_session_path(user_id: int) -> Path:
  return NETSCHOOL_SESSIONS_DIR / f"session_{user_id}.json"

def _get_proxy_for_netschool_url(url: str) -> str | None:
  for host, proxy in PROXY_REQUIRED_HOSTS.items():
    if host in url:
      return proxy
  return None


def _make_netschool_client(url: str):
  """Клиент «Сетевого города» с учётом региональных прокси."""
  return _make_netschool(url)


async def _login_netschool_client(user_id: int, user_data: dict):
  user_url = user_data.get("netschool_url")
  if not user_url:
    raise RuntimeError("В профиле не указан адрес NetSchool.")

  login = user_data.get("login")
  password = user_data.get("password")
  login_type = user_data.get("login_type", "password")
  school_raw = user_data.get("netschool_school")
  if isinstance(school_raw, int):
    school = school_raw
  else:
    school_text = str(school_raw or "").strip()
    school = int(school_text) if school_text.isdigit() else (school_text or None)
  client = _make_netschool_client(user_url)

  restored = False
  session_path = _netschool_session_path(user_id)
  if session_path.exists():
    try:
      await client.import_session(session_path.read_text(encoding="utf-8"))
      restored = True
    except Exception:
      try:
        session_path.unlink(missing_ok=True)
      except Exception:
        pass

  if not restored:
    if login_type == "esia_qr":
      if hasattr(client, "_http"):
        if hasattr(client._http, "aclose"): await client._http.aclose()
        else: await client._http.close()
      else: await client.close()
      raise RuntimeError("QR-сессия истекла. Перезайдите в NetSchool через бота.")
    if not login or not password:
      if hasattr(client, "_http"):
        if hasattr(client._http, "aclose"): await client._http.aclose()
        else: await client._http.close()
      else: await client.close()
      raise RuntimeError("Для загрузки данных нужен действующий вход через бота.")
    try:
      if login_type == "esia":
        await client.login_via_gosuslugi(esia_login=login, esia_password=password, school=school, timeout=60)
      else:
        await client.login(user_name=login, password=password, school=school, timeout=60)
      try:
        session_path.write_text(client.export_session(), encoding="utf-8")
      except Exception:
        pass
    except Exception as exc:
      err_text = str(exc or "").strip().lower()
      # Some accounts fail with a stale school binding; retry once without school.
      if school and ("401" in err_text or "unauthor" in err_text or "forbidden" in err_text):
        try:
          if login_type == "esia":
            await client.login_via_gosuslugi(esia_login=login, esia_password=password, school=None, timeout=60)
          else:
            await client.login(user_name=login, password=password, school=None, timeout=60)
          try:
            session_path.write_text(client.export_session(), encoding="utf-8")
          except Exception:
            pass
          exc = None
        except Exception as retry_exc:
          exc = retry_exc
      if exc is None:
        pass
      else:
        if hasattr(client, "_http"):
          if hasattr(client._http, "aclose"): await client._http.aclose()
          else: await client._http.close()
        else: await client.close()
        err_msg = str(exc or "").strip() or type(exc).__name__
        raise RuntimeError(f"Не удалось войти в NetSchool: {err_msg}") from exc

  # Switch to selected student if configured
  try:
    saved_student_id = _safe_positive_int(user_data.get("netschool_student_id"))
    if saved_student_id and getattr(client, '_student_id', None) != saved_student_id:
      await client.switch_student(saved_student_id)
  except Exception as e:
    logger.warning(f"Miniapp: Could not switch to student {saved_student_id}: {e}")

  return client

def _safe_int(value) -> int | None:
  try:
    return int(value)
  except Exception:
    return None

def _safe_positive_int(value) -> int | None:
  parsed = _safe_int(value)
  if parsed is None or parsed <= 0:
    return None
  return parsed

def _extract_students_from_diary_info(diary_info: dict) -> tuple[list[dict], int | None]:
  raw_students = diary_info.get("students") or {}
  current_raw = diary_info.get("currentStudentId")
  current_id = _safe_positive_int(current_raw)
  normalized: list[dict] = []

  if isinstance(raw_students, dict):
    items = list(raw_students.items())
  elif isinstance(raw_students, list):
    items = list(enumerate(raw_students))
  else:
    items = []
  for key, student in items:
    if not isinstance(student, dict):
      continue
    sid = _safe_positive_int(student.get("studentId"))
    if sid is None:
      sid = _safe_positive_int(key)
    if sid is None:
      continue
    name = (
      str(student.get("fio") or "").strip()
      or str(student.get("fullName") or "").strip()
      or str(student.get("name") or "").strip()
      or f"Ученик {sid}"
    )
    normalized.append({"id": sid, "name": name, "is_current": current_id is not None and sid == current_id})
  if current_id is None and normalized:
    current_id = normalized[0]["id"]
  return normalized, current_id

async def _sync_selected_student(client, user_id: int, user_data: dict, *, persist: bool = True) -> tuple[list[dict], int | None]:
  response = await client._authed_get("student/diary/init")
  diary_info = response.json()
  # Refresh school year context after restored sessions; stale year_id can lead to 401 on diary calls.
  year_id = _safe_positive_int(
    diary_info.get("yearId")
    or diary_info.get("currentYearId")
    or diary_info.get("schoolYearId")
    or diary_info.get("currentSchoolYearId")
  )
  if year_id is not None:
    try:
      setattr(client, "_year_id", int(year_id))
    except Exception:
      pass
  students, current_id = _extract_students_from_diary_info(diary_info)
  selected_raw = _safe_positive_int(user_data.get("selected_student_id"))
  available_ids = {item["id"] for item in students}
  selected_id = selected_raw if selected_raw in available_ids else current_id
  if selected_id is not None:
    try:
      setattr(client, "_student_id", int(selected_id))
    except Exception:
      pass
  changed = False
  normalized_students = [{"id": item["id"], "name": item["name"]} for item in students]
  if user_data.get("available_students") != normalized_students:
    user_data["available_students"] = normalized_students
    changed = True
  if selected_id is not None and _safe_int(user_data.get("selected_student_id")) != int(selected_id):
    user_data["selected_student_id"] = int(selected_id)
    changed = True
  selected_name = next((item["name"] for item in students if selected_id is not None and item["id"] == selected_id), None)
  if selected_name and user_data.get("student_name") != selected_name:
    user_data["student_name"] = selected_name
    changed = True
  if changed:
    user_data["updated_at"] = datetime.now().isoformat()
    if persist:
      _save_netschool_user_data(user_id, user_data)
  return normalized_students, selected_id

def _is_netschool_auth_error(exc: Exception) -> bool:
  text = str(exc or "").lower()
  markers = (
    "401",
    "403",
    "auth",
    "unauthor",
    "forbidden",
    "session",
    "expired",
    "login",
    "сесс",
    "истек",
  )
  return any(marker in text for marker in markers)

def _is_netschool_transient_error(exc: Exception) -> bool:
  text = str(exc or "").lower()
  markers = (
    "timeout",
    "connecttimeout",
    "readtimeout",
    "temporarily unavailable",
    "connection reset",
    "connection aborted",
    "network is unreachable",
    "timed out",
  )
  return any(marker in text for marker in markers)

def _classify_netschool_exception(exc: Exception) -> tuple[dict, int, bool]:
  """Map internal NetSchool exception to user-facing API payload.

  Returns: (payload, http_status, should_show_session_recovery)
  """
  text_raw = str(exc or "").strip()
  text = text_raw.lower()

  def _has(*markers: str) -> bool:
    return any(marker in text for marker in markers)

  is_diary_context = _has("student/diary", "diary/init", "/diary?")
  is_site_context = _has("sgo.", "webapi", "logindata", "api_url")

  if "не удалось войти в netschool" in text:
    transient_login_markers = (
      "timeout",
      "connecttimeout",
      "readtimeout",
      "network is unreachable",
      "host unreachable",
      "proxyerror",
      "connection reset",
      "connection aborted",
      "temporarily unavailable",
      "service unavailable",
      "502",
      "503",
      "504",
    )
    if any(marker in text for marker in transient_login_markers):
      if is_site_context:
        msg = "Сайт NetSchool сейчас недоступен. Попробуйте позже."
      else:
        msg = "Сервер NetSchool временно недоступен. Попробуйте обновить данные позже."
      return (
        {
          "error": msg,
          "error_code": "netschool_unavailable",
        },
        503,
        False,
      )
    invalid_markers = (
      "401",
      "403",
      "unauthor",
      "forbidden",
      "invalid",
      "wrong",
      "bad credentials",
      "loginerror",
      "невер",
      "логин",
      "парол",
    )
    if any(marker in text for marker in invalid_markers):
      return (
        {
          "error": "Неверный логин или пароль NetSchool. Перевойдите через бота и обновите данные входа.",
          "error_code": "invalid_credentials",
        },
        403,
        False,
      )
    return (
      {
        "error": "Не удалось выполнить вход в NetSchool. Проверьте данные аккаунта и попробуйте снова.",
        "error_code": "login_failed",
      },
      401,
      True,
    )

  transient_markers = (
    "timeout",
    "connecttimeout",
    "readtimeout",
    "network is unreachable",
    "host unreachable",
    "proxyerror",
    "connection reset",
    "connection aborted",
    "temporarily unavailable",
    "service unavailable",
    "502",
    "503",
    "504",
  )
  if any(marker in text for marker in transient_markers):
    if is_diary_context:
      msg = "Сервер дневника NetSchool временно недоступен. Показаны сохраненные данные."
    elif is_site_context:
      msg = "Сайт NetSchool сейчас недоступен. Попробуйте позже."
    elif _has("timeout", "connecttimeout", "readtimeout", "timed out"):
      msg = "NetSchool долго отвечает (таймаут). Попробуйте позже."
    else:
      msg = "Сервер NetSchool временно недоступен. Попробуйте обновить данные позже."
    return (
      {
        "error": msg,
        "error_code": "netschool_unavailable",
      },
      503,
      False,
    )

  if "409" in text and "login" in text:
    return (
      {
        "error": "NetSchool временно перегружен. Попробуйте снова через 1-2 минуты.",
        "error_code": "netschool_busy",
      },
      503,
      False,
    )

  if _is_netschool_auth_error(exc):
    return (
      {
        "error": "Сессия NetSchool истекла. Войдите повторно.",
        "error_code": "session_expired",
      },
      401,
      True,
    )

  return (
    {
      "error": "Ошибка NetSchool. Попробуйте обновить позже.",
      "error_code": "netschool_error",
    },
    500,
    False,
  )

def _netschool_error_response(exc: Exception, *, clear_miniapp_session: bool = True):
  payload, status, should_recover = _classify_netschool_exception(exc)
  if clear_miniapp_session and should_recover:
    session.pop("netschool_miniapp_user_id", None)
  return jsonify(payload), status

_miniapp_autosave_started = False

def _get_miniapp_autosave_user_ids() -> list[int]:
  store = _normalize_miniapp_token_store(_load_json_file(NETSCHOOL_MINIAPP_TOKENS_FILE, {"tokens": {}}))
  ids: set[int] = set()
  for payload in (store.get("tokens") or {}).values():
    user_id = _safe_positive_int((payload or {}).get("user_id"))
    if user_id is not None:
      ids.add(user_id)
  return sorted(ids)

def _run_miniapp_hourly_autosave_cycle() -> None:
  user_ids = _get_miniapp_autosave_user_ids()
  if not user_ids:
    return
  for user_id in user_ids:
    user_data = _get_netschool_user_by_id(user_id)
    if not user_data:
      continue
    try:
      payload = _run_async(_fetch_diary_bundle_live(int(user_id), user_data))
      user_data["last_sync_at"] = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
      user_data["updated_at"] = datetime.now().isoformat()
      _save_netschool_user_data(int(user_id), user_data)
      payload["is_cached"] = False
      payload["profile"] = _build_netschool_appearance_payload(user_data)
      _save_netschool_miniapp_cache_section(int(user_id), "dashboard", payload)
    except Exception as exc:
      logger.warning(f"Miniapp autosave dashboard failed for user {user_id}: {exc}")

    try:
      async def _load_totals(client):
        return await _fetch_student_total_marks_report(client)
      marks = _run_async(_run_netschool_request(int(user_id), user_data, _load_totals))
      _save_netschool_miniapp_cache_section(int(user_id), "totals", {
        "totals": _normalize_total_marks_rows(marks),
        "fallback": False,
      })
    except Exception as exc:
      logger.warning(f"Miniapp autosave totals failed for user {user_id}: {exc}")

def _start_miniapp_autosave_worker_once() -> None:
  global _miniapp_autosave_started
  if _miniapp_autosave_started:
    return
  _miniapp_autosave_started = True

  def _worker():
    time.sleep(15)
    while True:
      try:
        _run_miniapp_hourly_autosave_cycle()
      except Exception as exc:
        logger.warning(f"Miniapp autosave cycle failed: {exc}")
      time.sleep(NETSCHOOL_MINIAPP_AUTOSAVE_INTERVAL_SECONDS)

  threading.Thread(target=_worker, name="miniapp-autosave", daemon=True).start()

async def _run_netschool_request(user_id: int, user_data: dict, operation):
  async def _execute_once():
    client = await _login_netschool_client(user_id, user_data)
    try:
      selected_id = _safe_positive_int(user_data.get("selected_student_id"))
      if selected_id is not None:
        try:
          setattr(client, "_student_id", selected_id)
        except Exception:
          pass
      try:
        await _sync_selected_student(client, user_id, user_data, persist=True)
      except Exception:
        pass
      return await operation(client)
    finally:
      if hasattr(client, "_http"):
        if hasattr(client._http, "aclose"): await client._http.aclose()
        else: await client._http.close()
      else: await client.close()

  attempts = 3
  delay = 1.5
  last_exc: Exception | None = None
  for attempt in range(attempts):
    try:
      return await _execute_once()
    except Exception as exc:
      last_exc = exc
      if _is_netschool_auth_error(exc):
        try:
          _netschool_session_path(user_id).unlink(missing_ok=True)
        except Exception:
          pass
      elif not _is_netschool_transient_error(exc):
        raise
      if attempt >= attempts - 1:
        raise
      await asyncio.sleep(delay)
      delay = min(delay * 2, 6.0)
  if last_exc is not None:
    raise last_exc
  raise RuntimeError("Не удалось выполнить запрос NetSchool")

def _run_async(coro):
  return asyncio.run(coro)

def _normalize_total_marks_rows(marks) -> list[dict]:
  rows: list[dict] = []
  for m in (marks or []):
    if isinstance(m, dict):
      subject = m.get("subject") or "—"
      period_marks = m.get("period_marks")
      year_mark = m.get("year_mark")
      exam_mark = m.get("exam_mark")
      final_mark = m.get("final_mark")
    else:
      subject = getattr(m, "subject", "—")
      period_marks = getattr(m, "period_marks", None)
      year_mark = getattr(m, "year_mark", None)
      exam_mark = getattr(m, "exam_mark", None)
      final_mark = getattr(m, "final_mark", None)
    rows.append({
      "subject": subject,
      "period_marks": period_marks,
      "year_mark": year_mark,
      "exam_mark": exam_mark,
      "final_mark": final_mark,
    })
  return rows

async def _fetch_student_total_marks_report(client) -> list[dict]:
  if hasattr(client, "total_marks"):
    return _normalize_total_marks_rows(await client.total_marks())
  if hasattr(client, "totals_marks"):
    return _normalize_total_marks_rows(await client.totals_marks())

  try:
    import websockets
  except Exception as exc:
    raise RuntimeError(f"Официальный отчёт недоступен: не установлен websockets ({exc})")

  filters_resp = await client._authed_get("reports/studenttotalmarks")
  filters = filters_resp.json() if hasattr(filters_resp, "json") else {}

  students = (filters or {}).get("students") or []
  classes = (filters or {}).get("pcLs") or []
  if not students or not classes:
    raise RuntimeError("Официальный отчёт StudentTotalMarks недоступен для этой школы/учётной записи.")

  student_id = (students[0] or {}).get("value")
  class_id = (classes[0] or {}).get("value")
  if not student_id or not class_id:
    raise RuntimeError("Официальный отчёт StudentTotalMarks вернул пустые фильтры.")

  await client._authed_get("earlyaccess?accessKey=irtechsignalr&url=%2F")

  queue_resp = await client._authed_post(
    "reports/studenttotalmarks/queue",
    json={"studentId": student_id, "classId": class_id},
  )
  queue_data = queue_resp.json() if hasattr(queue_resp, "json") else {}
  task_id = (queue_data or {}).get("taskId")
  queue_key = (queue_data or {}).get("queueKey")
  if not task_id or not queue_key:
    raise RuntimeError(f"Ошибка постановки отчёта в очередь: {queue_data}")

  ws_url = f"{client.api_url}/queueHub?token={client._at}".replace("http", "ws", 1)
  cookie_header = ""
  for holder in [getattr(client, "session", None), getattr(client, "_session", None)]:
    jar = getattr(holder, "cookies", None)
    if jar:
      try:
        cookie_header = "; ".join([f"{k}={v}" for k, v in jar.items()])
        if cookie_header:
          break
      except Exception:
        pass

  handshake_msg = json.dumps({"protocol": "json", "version": 1}) + "\x1e"
  invoke_msg = json.dumps({
    "arguments": [task_id, queue_key],
    "invocationId": "0",
    "target": "startTaskAsync",
    "type": 1,
  }) + "\x1e"

  complete_file_id = None
  connect_kwargs = {}
  if cookie_header:
    connect_kwargs["additional_headers"] = {"Cookie": cookie_header}
  try:
    ws_ctx = websockets.connect(ws_url, **connect_kwargs)
  except TypeError:
    connect_kwargs = {"extra_headers": {"Cookie": cookie_header}} if cookie_header else {}
    ws_ctx = websockets.connect(ws_url, **connect_kwargs)

  try:
    async with ws_ctx as ws:
      await ws.send(handshake_msg)
      await ws.recv()
      await ws.send(invoke_msg)

      start_time = asyncio.get_event_loop().time()
      while asyncio.get_event_loop().time() - start_time < 70:
        raw_msg = await asyncio.wait_for(ws.recv(), timeout=8.0)
        for msg_str in str(raw_msg).split("\x1e"):
          if not msg_str:
            continue
          msg = json.loads(msg_str)
          if msg.get("type") == 3 and msg.get("invocationId") == "0":
            if "error" in msg:
              raise RuntimeError(f"Ошибка SignalR: {msg.get('error')}")
            result = msg.get("result") or {}
            if result.get("success") is False:
              raise RuntimeError(f"Ошибка генерации отчёта: {result.get('message')}")
          if msg.get("type") == 1 and msg.get("target") == "complete":
            args = msg.get("arguments") or []
            if args and isinstance(args[0], dict) and args[0].get("data"):
              complete_file_id = args[0]["data"]
              break
        if complete_file_id:
          break
  except Exception as exc:
    raise RuntimeError(f"Ошибка WebSocket/SignalR при генерации официального отчёта: {exc}") from exc

  if not complete_file_id:
    raise RuntimeError("Не удалось получить fileId официального отчёта (таймаут).")

  file_resp = await client._authed_get(f"files/{complete_file_id}")
  html_content = getattr(file_resp, "text", "") or ""

  rows = re.findall(r"<tr.*?>(.*?)</tr>", html_content, flags=re.IGNORECASE | re.DOTALL)

  def _clean_html(raw_html: str) -> str:
    cleantext = re.sub(r"<.*?>", "", raw_html)
    return html.unescape(cleantext).strip()

  result_rows: list[dict] = []
  for row in rows:
    cols = list(re.finditer(r"<t[dh].*?>(.*?)</t[dh]>", row, flags=re.IGNORECASE | re.DOTALL))
    if not cols:
      continue
    col_texts = [_clean_html(m.group(1)) for m in cols]
    if len(col_texts) < 5:
      continue
    try:
      int(col_texts[0])
    except Exception:
      continue
    subject = col_texts[1]
    grades = col_texts[2:]
    year_mark = grades[-3] if len(grades) >= 3 and grades[-3] else None
    exam_mark = grades[-2] if len(grades) >= 2 and grades[-2] else None
    final_mark = grades[-1] if len(grades) >= 1 and grades[-1] else None
    period_marks = [g if g else None for g in grades[:-3]]
    result_rows.append({
      "subject": subject,
      "period_marks": period_marks,
      "year_mark": year_mark,
      "exam_mark": exam_mark,
      "final_mark": final_mark,
    })

  return result_rows

def _extract_mark_value(mark):
    if mark is None:
        return None
    if hasattr(mark, "textMark") and getattr(mark, "textMark", None):
        return getattr(mark, "textMark")
    if hasattr(mark, "mark"):
        mark_val = getattr(mark, "mark", None)
        if hasattr(mark_val, "textMark") and getattr(mark_val, "textMark", None):
            return getattr(mark_val, "textMark")
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

def _mark_to_int(mark) -> int | None:
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

def _clean_netschool_text(value: str | None) -> str:
  if not value:
    return ""
  return re.sub(r"\s+", " ", str(value)).strip()

def _is_displayable_mark(value) -> bool:
  normalized = _clean_netschool_text(value)
  if not normalized:
    return False
  if _mark_to_int(normalized) is not None:
    return True
  # Ignore non-grade placeholders/statuses so diary does not show phantom marks.
  return bool(re.match(r"^(зач|незач|осв|н/а|н)$", normalized, flags=re.IGNORECASE))

def _extract_lesson_topic(lesson) -> str:
  candidates = [
    getattr(lesson, "topic", None),
    getattr(lesson, "theme", None),
    getattr(lesson, "lesson_theme", None),
    getattr(lesson, "lessonTopic", None),
    getattr(lesson, "name", None),
    getattr(lesson, "title", None),
  ]
  for raw in candidates:
    topic = _clean_netschool_text(raw)
    if topic:
      return topic
  return ""

def _format_mark_entered_label(raw_value, fallback_day: date) -> str:
  if isinstance(raw_value, datetime):
    return raw_value.strftime("%d.%m.%Y")
  if isinstance(raw_value, date):
    return raw_value.strftime("%d.%m.%Y")
  raw = _clean_netschool_text(raw_value)
  if raw:
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if match:
      try:
        parsed = datetime.strptime(match.group(0), "%Y-%m-%d").date()
        return parsed.strftime("%d.%m.%Y")
      except Exception:
        pass
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", raw)
    if match:
      return match.group(0)
  return fallback_day.strftime("%d.%m.%Y")

def _upcoming_school_dates(limit: int = 5) -> set:
  current = datetime.now(timezone(timedelta(hours=3))).date()
  result = set()
  while len(result) < limit:
    if current.weekday() < 5:
      result.add(current)
    current += timedelta(days=1)
  return result

async def _fetch_diary_bundle_live(user_id: int, user_data: dict) -> dict:
  async def _load_days(client):
    today = datetime.now(timezone(timedelta(hours=3))).date()
    start_date = _academic_year_start(today)
    max_date = today + timedelta(days=60)
    current = start_date - timedelta(days=start_date.weekday())
    
    weeks_to_fetch = []
    while current <= max_date:
        weeks_to_fetch.append(current)
        current += timedelta(days=7)
        
    days_by_date = {}
    sem = asyncio.Semaphore(7)
    week_errors: list[str] = []
    
    async def fetch_week(date):
      async with sem:
        try:
          return await client.diary(start=date)
        except Exception as exc:
          week_errors.append(str(exc) or type(exc).__name__)
          return None
                
    results = await asyncio.gather(*(fetch_week(d) for d in weeks_to_fetch))
    
    loaded_weeks = 0
    for diary in results:
      if not diary:
        continue
      loaded_weeks += 1
      for day in getattr(diary, "schedule", []) or []:
        day_date = getattr(day, "day", None)
        if day_date:
          days_by_date[day_date] = day

    if loaded_weeks == 0 and weeks_to_fetch:
      details = week_errors[0] if week_errors else "неизвестная ошибка"
      raise RuntimeError(f"Не удалось загрузить дневник: {details}")
                
    students_list = []
    if hasattr(client, "students"):
        for s in getattr(client, "students") or []:
            students_list.append({"id": getattr(s, "id"), "name": getattr(s, "name")})
    if not students_list:
      for s in user_data.get("available_students") or []:
        sid = _safe_positive_int((s or {}).get("id"))
        sname = str((s or {}).get("name") or "").strip()
        if sid is not None and sname:
          students_list.append({"id": sid, "name": sname})
            
    return start_date, max_date, days_by_date, students_list

  start_date, max_date, days_by_date, students_list = await _run_netschool_request(user_id, user_data, _load_days)

  attachment_lookup: dict[int, list[dict]] = {}
  attachment_start = datetime.now(timezone(timedelta(hours=3))).date() - timedelta(days=7)
  attachment_end = datetime.now(timezone(timedelta(hours=3))).date() + timedelta(days=14)
  assignment_ids: list[int] = []
  for day_date, day in days_by_date.items():
    if day_date < attachment_start or day_date > attachment_end:
      continue
    for lesson in getattr(day, "lessons", []) or []:
      for assignment in getattr(lesson, "assignments", []) or []:
        assignment_id = getattr(assignment, "id", None)
        if assignment_id:
          assignment_ids.append(int(assignment_id))

  if assignment_ids:
    async def _load_attachments(client):
      async def _fetch_one(assignment_id: int):
        if assignment_id in attachment_lookup:
          return
        try:
          attachments = await client.attachments(assignment_id)
        except Exception:
          attachments = []
        attachment_lookup[assignment_id] = [
          {"id": int(getattr(att, "id", 0)), "name": getattr(att, "name", None) or f"file_{getattr(att, 'id', '')}"}
          for att in attachments if getattr(att, "id", None)
        ]
      await asyncio.gather(*[_fetch_one(assignment_id) for assignment_id in sorted(set(assignment_ids))])

    await _run_netschool_request(user_id, user_data, _load_attachments)

  all_grade_items = []
  grouped_subjects = {}
  finals = []
  homework = []
  diary_days = []
  today = datetime.now(timezone(timedelta(hours=3))).date()
  quarter_meta = _quarter_ranges(today)
  quarter_labels = {key: label for key, label, _start, _end in quarter_meta}
  quarter_end_dates = {key: _end for key, _label, _start, _end in quarter_meta}

  current_day = start_date
  while current_day <= max_date:
    day = days_by_date.get(current_day)
    schedule_lessons = []
    day_homework_count = 0
    day_mark_count = 0
    # Sort lessons by API number so they appear in schedule order
    raw_lessons = sorted(getattr(day, "lessons", []) or [], key=lambda ln: getattr(ln, "number", 999)) if day is not None else []
    for display_num, lesson in enumerate(raw_lessons, start=1):
      subject = getattr(lesson, "subject", "") or "Без названия"
      lesson_topic = _extract_lesson_topic(lesson)
      room = _clean_netschool_text(getattr(lesson, "room", None) or getattr(lesson, "classroom", None))
      start_time = getattr(lesson, "start", None)
      end_time = getattr(lesson, "end", None)
      time_label = ""
      if start_time and end_time:
        time_label = f"{start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"
      elif start_time:
        time_label = start_time.strftime('%H:%M')
      lesson_marks = []
      # Extract homework text from assignments (Lesson model has no .homework)
      hw_parts = []
      hw_attachments = []
      hw_details = []
      hw_attachment_ids = set()
      hw_unspecified = False
      for assignment in getattr(lesson, "assignments", []) or []:
        a_content = _clean_netschool_text(getattr(assignment, "content", None))
        a_kind = _clean_netschool_text(getattr(assignment, "kind", None) or getattr(assignment, "type", None) or "")
        a_atts = []
        raw_attachments = list(getattr(assignment, "attachments", []) or [])
        if not raw_attachments and getattr(assignment, "id", None):
          raw_attachments = attachment_lookup.get(int(getattr(assignment, "id")), []) or []
        for att in raw_attachments:
          att_id = getattr(att, "id", None) if not isinstance(att, dict) else att.get("id")
          att_name = (getattr(att, "name", None) if not isinstance(att, dict) else att.get("name")) or f"file_{att_id}"
          if att_id:
            att_key = int(att_id)
            if att_key not in {int(item.get("id")) for item in a_atts if item.get("id") is not None}:
              a_atts.append({"id": att_key, "name": att_name})
            if att_key not in hw_attachment_ids:
              hw_attachment_ids.add(att_key)
              hw_attachments.append({"id": att_key, "name": att_name})
        valid_content = bool(a_content and a_content.strip() not in ("---Не указана---", "Не указана"))
        if a_content in ("---Не указана---", "Не указана"):
          hw_unspecified = True
        if valid_content:
          hw_parts.append(a_content)
        if valid_content or a_atts:
          hw_details.append({"text": a_content, "kind": a_kind, "attachments": a_atts})
        mark_value = _extract_mark_value(assignment)
        if mark_value is None or not _is_displayable_mark(mark_value):
          continue
        mark_entered_raw = (
          getattr(assignment, "date", None)
          or getattr(assignment, "mark_date", None)
          or getattr(assignment, "markDate", None)
          or getattr(assignment, "grade_date", None)
          or getattr(assignment, "gradeDate", None)
          or getattr(assignment, "dateAssigned", None)
          or getattr(assignment, "date_assigned", None)
          or getattr(assignment, "created_at", None)
          or getattr(assignment, "created", None)
          or getattr(assignment, "createdDate", None)
          or getattr(assignment, "updated_at", None)
          or getattr(assignment, "updatedDate", None)
        )
        mark_entered_label = _format_mark_entered_label(mark_entered_raw, current_day)
        item = {
          "date": current_day.strftime("%d.%m.%Y"),
          "date_label": current_day.strftime("%d.%m"),
          "date_sort": current_day.isoformat(),
          "quarter": _quarter_key_for_date(current_day, today),
          "subject": subject,
          "title": _clean_netschool_text(getattr(assignment, "kind", None) or getattr(assignment, "type", None) or "Задание"),
          "mark": str(mark_value),
          "mark_int": _mark_to_int(mark_value),
          "weight": getattr(assignment, "weight", None) or 1,
          "entered_at_label": mark_entered_label,
        }
        all_grade_items.append(item)
        grouped_subjects.setdefault(subject, []).append(item)
        day_mark_count += 1
        lesson_marks.append({
          "mark": item["mark"],
          "title": item["title"],
          "weight": item["weight"],
          "date_label": item["date_label"],
          "entered_at_label": mark_entered_label,
          "comment": _clean_netschool_text(getattr(assignment, "comment", None)),
        })

      homework_text = " | ".join(hw_parts) if hw_parts else ("Не указана" if hw_unspecified else "")
      has_homework = bool(homework_text or hw_attachments or hw_unspecified)
      if has_homework and current_day >= (today - timedelta(days=14)):
        day_homework_count += 1
        homework.append({
          "date": current_day.strftime("%d.%m.%Y"),
          "date_label": current_day.strftime("%d.%m"),
          "weekday": ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"][current_day.weekday()],
          "subject": subject,
          "text": homework_text,
          "attachments": hw_attachments,
          "hw_details": hw_details,
          "lesson_number": display_num,
          "room": room,
          "time": time_label or "",
          "sort_date": current_day.isoformat(),
          "unspecified": hw_unspecified,
        })

      schedule_lessons.append({
        "number": display_num,
        "source_index": display_num - 1,
        "subject": subject,
        "topic": lesson_topic,
        "room": room,
        "time": time_label or "",
        "homework": homework_text,
        "has_homework": has_homework,
        "hw_attachments": hw_attachments,
        "hw_attachments_count": len(hw_attachments),
        "hw_details": hw_details,
        "hw_unspecified": hw_unspecified,
        "marks": lesson_marks,
      })

    diary_days.append({
      "date": current_day.isoformat(),
      "date_label": current_day.strftime("%d.%m"),
      "display_date": current_day.strftime("%d.%m.%Y"),
      "weekday": ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"][current_day.weekday()],
      "weekday_short": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][current_day.weekday()],
      "is_today": current_day == today,
      "lesson_count": len(schedule_lessons),
      "homework_count": day_homework_count,
      "mark_count": day_mark_count,
      "lessons": schedule_lessons,
    })
    current_day += timedelta(days=1)

  all_grade_items.sort(key=lambda item: item["date_sort"], reverse=True)
  subjects_payload = []
  for subject, items in sorted(grouped_subjects.items()):
    items.sort(key=lambda item: item["date_sort"], reverse=True)
    numeric = [item["mark_int"] for item in items if item.get("mark_int") is not None]
    weighted_pairs = [(item["mark_int"], item.get("weight", 1) or 1) for item in items if item.get("mark_int") is not None]
    quarter_values = {key: [] for key in quarter_labels}
    for item in items:
      quarter_key = item.get("quarter")
      mark_int = item.get("mark_int")
      weight = item.get("weight", 1) or 1
      if quarter_key in quarter_values and mark_int is not None:
        quarter_values[quarter_key].append((mark_int, weight))

    def _weighted_avg(pairs):
      if not pairs:
        return None
      total_w = sum(w for _, w in pairs)
      if total_w == 0:
        return None
      return round(sum(m * w for m, w in pairs) / total_w, 2)

    quarters = {}
    for key, pairs in quarter_values.items():
      avg = _weighted_avg(pairs)
      is_past = quarter_end_dates.get(key, today) < today
      estimated_final = None
      if avg is not None and len(pairs) >= 1:
        estimated_final = str(math.floor(avg + 0.5))
      quarters[key] = {
        "label": quarter_labels[key],
        "average": avg,
        "count": len(pairs),
        "display": f"{avg:.2f}" if avg is not None else "—",
        "is_past": is_past,
        # Official final grade is not available in diary payload; keep it empty.
        "final_grade": None,
        "estimated_final_grade": estimated_final,
      }
    average = _weighted_avg(weighted_pairs)
    if average is not None:
      finals.append({
        "subject": subject,
        "average": f"{average:.2f}",
        "count": len(weighted_pairs),
      })
    subjects_payload.append({
      "subject": subject,
      "count": len(items),
      "average": average,
      "average_label": f"{average:.2f}" if average is not None else "нет ср. балла",
      "quarters": quarters,
      "items": items,
    })

  finals.sort(key=lambda item: float(item["average"]), reverse=True)
  diary_days.sort(key=lambda item: item["date"])
  homework.sort(key=lambda item: item["sort_date"])
  recent_numeric = [item["mark_int"] for item in all_grade_items if item.get("mark_int") is not None][:10]
  today_iso = today.isoformat()
  selected_day = next((day for day in diary_days if day.get("is_today")), None)
  if not selected_day:
    selected_day = next((day for day in diary_days if day.get("date", "") >= today_iso), None)
  if not selected_day and diary_days:
    selected_day = diary_days[-1]
  cache_path = _netschool_cache_path(user_id)
  cache_homework_text = ""
  if cache_path.exists():
    try:
      cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
      cache_homework_text = ((cache_data.get("homework") or {}).get("text") or "").strip()
    except Exception:
      pass

  return {
    "recent_grades": all_grade_items[:12],
    "subjects": subjects_payload,
    "finals": finals[:12],
    "homework": [{k: v for k, v in item.items() if k != "sort_date"} for item in homework[:30]],
    "diary_days": diary_days,
    "schedule_days": diary_days,
    "quarter_columns": [{"key": key, "label": label} for key, label in quarter_labels.items()],
    "current_quarter_key": _quarter_key_for_date(today, today),
    "current_quarter_label": _current_quarter_label(today),
    "selected_date": selected_day["date"] if selected_day else None,
    "summary": {
      "today_lessons": selected_day["lesson_count"] if selected_day else 0,
      "today_label": f"{selected_day['weekday']}, {selected_day['display_date']}" if selected_day else "Нет учебных дней",
      "upcoming_homework": len(homework[:20]),
      "homework_label": "На ближайшие даты",
      "recent_average": f"{(sum(recent_numeric) / len(recent_numeric)):.2f}" if recent_numeric else "—",
      "average_label": "По последним числовым оценкам",
    },
    "homework_text": cache_homework_text,
    "students": students_list,
  }

async def _fetch_mail_list_live(user_id: int, user_data: dict, *, page: int = 1, page_size: int = 20) -> dict:
  async def _load_mail(client):
    mail_page = await client.mail_list(folder="Inbox", page=max(1, page), page_size=max(1, min(page_size, 50)))
    unread_ids = await client.mail_unread()
    return mail_page.entries or [], unread_ids or []

  entries, unread_ids = await _run_netschool_request(user_id, user_data, _load_mail)
  seen_ids = set(_normalize_mail_seen_ids(user_data.get("mail_seen_ids") or []))
  unread_id_set = set(_normalize_mail_seen_ids(unread_ids or [], limit=5000))
  unread_count = sum(1 for message_id in unread_id_set if message_id not in seen_ids)
  normalized_seen_ids = sorted(seen_ids, reverse=True)[:500]
  if normalized_seen_ids != list(user_data.get("mail_seen_ids") or []) or int(user_data.get("mail_unread_count") or 0) != unread_count:
    user_data["mail_seen_ids"] = normalized_seen_ids
    user_data["mail_unread_count"] = unread_count
    user_data["updated_at"] = datetime.now().isoformat()
    _save_netschool_user_data(int(user_id), user_data)
  return {
    "page": max(1, page),
    "page_size": max(1, min(page_size, 50)),
    "has_more": len(entries) >= max(1, min(page_size, 50)),
    "unread_count": unread_count,
    "entries": [
      {
        "id": entry.id,
        "subject": entry.subject or "(без темы)",
        "author": entry.author or "—",
        "sent": entry.sent.strftime("%d.%m.%Y %H:%M"),
        "unread": entry.id in unread_id_set and entry.id not in seen_ids,
      }
      for entry in entries
    ]
  }

async def _fetch_homework_detail_live(user_id: int, user_data: dict, target_date: date, lesson_index: int) -> dict:
  async def _load_detail(client):
    diary = await client.diary(start=target_date, end=target_date)
    day = next((item for item in (getattr(diary, "schedule", []) or []) if getattr(item, "day", None) == target_date), None)
    lessons = sorted(getattr(day, "lessons", []) or [], key=lambda lesson: getattr(lesson, "number", 999))
    if lesson_index < 0 or lesson_index >= len(lessons):
      raise RuntimeError("Задание не найдено.")
    lesson = lessons[lesson_index]
    homework_parts = []
    attachments = []
    details = []
    seen_attachment_ids = set()
    unspecified = False
    for assignment in getattr(lesson, "assignments", []) or []:
      assignment_text = _clean_netschool_text(getattr(assignment, "content", None))
      assignment_kind = _clean_netschool_text(getattr(assignment, "kind", None) or getattr(assignment, "type", None) or "")
      assignment_attachments = []
      raw_attachments = list(getattr(assignment, "attachments", []) or [])
      if not raw_attachments and getattr(assignment, "id", None):
        try:
          raw_attachments = list(await client.attachments(int(assignment.id)))
        except Exception:
          raw_attachments = []
      for attachment in raw_attachments:
        attachment_id = getattr(attachment, "id", None)
        attachment_name = getattr(attachment, "name", None) or f"file_{attachment_id}"
        if not attachment_id:
          continue
        payload = {"id": int(attachment_id), "name": attachment_name}
        assignment_attachments.append(payload)
        if int(attachment_id) not in seen_attachment_ids:
          seen_attachment_ids.add(int(attachment_id))
          attachments.append(payload)
      valid_text = bool(assignment_text and assignment_text.strip() not in ("---Не указана---", "Не указана"))
      if assignment_text in ("---Не указана---", "Не указана"):
        unspecified = True
      if valid_text:
        homework_parts.append(assignment_text)
      if valid_text or assignment_attachments:
        details.append({"text": assignment_text, "kind": assignment_kind, "attachments": assignment_attachments})
    room = _clean_netschool_text(getattr(lesson, "room", None) or getattr(lesson, "classroom", None))
    start_time = getattr(lesson, "start", None)
    end_time = getattr(lesson, "end", None)
    time_label = ""
    if start_time and end_time:
      time_label = f"{start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"
    elif start_time:
      time_label = start_time.strftime('%H:%M')
    return {
      "subject": getattr(lesson, "subject", "") or "Без названия",
      "text": " | ".join(homework_parts) if homework_parts else ("Не указана" if unspecified else ""),
      "attachments": attachments,
      "details": details,
      "unspecified": unspecified,
      "time": time_label,
      "room": room,
      "date": target_date.strftime("%d.%m.%Y"),
      "weekday": ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"][target_date.weekday()],
    }

  return await _run_netschool_request(user_id, user_data, _load_detail)

async def _fetch_mail_message_live(user_id: int, user_data: dict, message_id: int) -> dict:
  async def _load_mail(client):
    await _prime_netschool_mail_client(client)
    return await client.mail_read(message_id)

  mail = await _run_netschool_request(user_id, user_data, _load_mail)
  seen = set(_normalize_mail_seen_ids(user_data.get("mail_seen_ids") or []))
  was_unread = int(message_id) not in seen
  seen.add(message_id)
  user_data["mail_seen_ids"] = sorted(seen, reverse=True)[:500]
  current_unread_count = max(0, int(user_data.get("mail_unread_count") or 0))
  user_data["mail_unread_count"] = max(0, current_unread_count - 1) if was_unread else current_unread_count
  user_data["updated_at"] = datetime.now().isoformat()
  _save_netschool_user_data(int(user_id), user_data)
  return {
    "id": message_id,
    "subject": mail.subject or "(без темы)",
    "author": mail.author_name or "—",
    "to_names": mail.to_names or "—",
    "sent": mail.sent.strftime("%d.%m.%Y %H:%M"),
    "body": (mail.text or "(пусто)").strip(),
    "attachments": [
      {"id": attachment.id, "name": attachment.name}
      for attachment in (mail.file_attachments or [])
    ],
  }

async def _download_mail_attachment_live(user_id: int, user_data: dict, message_id: int, attachment_id: int) -> tuple[io.BytesIO, str]:
  async def _download(client):
    await _prime_netschool_mail_client(client)
    mail = await client.mail_read(message_id)
    attachments = [attachment for attachment in (mail.file_attachments or []) if int(getattr(attachment, "id", 0)) == int(attachment_id)]
    if not attachments:
      raise RuntimeError("Вложение не найдено.")
    buffer = io.BytesIO()
    await client.download_attachment(attachment_id, buffer, timeout=90)
    buffer.seek(0)
    return buffer, attachments[0].name or f"attachment_{attachment_id}"

  return await _run_netschool_request(user_id, user_data, _download)

@app.route("/mini/netschool")
def netschool_miniapp_page():
  token = request.args.get("token", "")
  if token:
    user_id = _validate_netschool_miniapp_token(token)
    if user_id:
      session.permanent = True
      session["netschool_miniapp_user_id"] = user_id
      return redirect(_external_url_for("netschool_miniapp_page"))
  user_data = _get_netschool_miniapp_user()
  if not user_data:
    session.pop("netschool_miniapp_user_id", None)
    if token and _request_invalid_token_recovery(token):
      return _render_netschool_miniapp_response(error="Ссылка PWA недействительна или устарела. Я отправил запрос в Telegram предыдущему владельцу ссылки: там можно отклонить вход или получить код для восстановления.")
    return _render_netschool_miniapp_response(error="Сессия мини-приложения недействительна или истекла. Вернитесь в бота и откройте панель заново.")
  return _render_netschool_miniapp_response(data=_build_netschool_miniapp_payload(user_data))

@app.route("/api/mini/netschool/state")
def netschool_miniapp_state():
  user_data = _get_netschool_miniapp_user()
  if not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  return jsonify(_build_netschool_miniapp_payload(user_data))

@app.route("/api/mini/netschool/pwa-link")
def netschool_miniapp_pwa_link():
  user_id = session.get("netschool_miniapp_user_id")
  if not user_id:
    return jsonify({"error": "Сессия недействительна"}), 401
  return jsonify({"url": _issue_netschool_pwa_link(int(user_id), revoke_existing=False)})

@app.route("/api/mini/netschool/pwa-link/reset", methods=["POST"])
def netschool_miniapp_pwa_link_reset():
  user_id = session.get("netschool_miniapp_user_id")
  if not user_id:
    return jsonify({"error": "Сессия недействительна"}), 401
  return jsonify({"url": _issue_netschool_pwa_link(int(user_id), revoke_existing=True)})

def _build_push_api_payload(user_id: int, user_data: dict) -> dict:
  profile = _build_netschool_miniapp_payload(user_data)
  return {
    "profile": profile,
    "push": {
      "configured": bool(profile.get("push_configured")),
      "subscription_count": int(profile.get("push_subscription_count") or 0),
      "status_label": profile.get("push_status_label") or "—",
      "public_key": profile.get("push_public_key") or "",
    }
  }

@app.route("/api/mini/netschool/push/subscribe", methods=["POST"])
def netschool_miniapp_push_subscribe():
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  payload = request.get_json(silent=True) or {}
  subscription = payload.get("subscription") or {}
  user_agent = str(payload.get("userAgent") or request.headers.get("User-Agent") or "")
  try:
    upsert_user_subscription(int(user_id), subscription, user_agent=user_agent)
    if str(user_data.get("push_mode") or "telegram") == "telegram":
      user_data["push_mode"] = "both"
      user_data["updated_at"] = datetime.now().isoformat()
      _save_netschool_user_data(int(user_id), user_data)
    return jsonify(_build_push_api_payload(int(user_id), user_data))
  except Exception as exc:
    return jsonify({"error": str(exc)}), 400

@app.route("/api/mini/netschool/push/unsubscribe", methods=["POST"])
def netschool_miniapp_push_unsubscribe():
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  payload = request.get_json(silent=True) or {}
  endpoint = str(payload.get("endpoint") or "").strip() or None
  remove_user_subscription(int(user_id), endpoint)
  return jsonify(_build_push_api_payload(int(user_id), user_data))

@app.route("/api/mini/netschool/push/test", methods=["POST"])
def netschool_miniapp_push_test():
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  payload = request.get_json(silent=True) or {}
  endpoint = payload.get("endpoint")
  payload = request.get_json(silent=True) or {}
  endpoint = payload.get("endpoint")
  base = _external_url_for("netschool_miniapp_page")
  result = send_user_push(
    int(user_id),
    title="NetSchool PWA",
    body="Тестовое уведомление отправлено успешно.",
    url=f"{base}#profile",
    tag="netschool-test",
    data={"tab": "profile"},
  )
  if not result.get("ok"):
    return jsonify({"error": "Не удалось доставить push на это устройство"}), 400
  return jsonify({
    **_build_push_api_payload(int(user_id), user_data),
    "message": "Тестовое уведомление отправлено"
  })

@app.route("/api/mini/netschool/student/switch", methods=["POST"])
def netschool_miniapp_switch_student():
  user_id = session.get("netschool_miniapp_user_id")
  if not user_id:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия истекла"}), 401
  user_data = _get_netschool_miniapp_user()
  if not user_data:
    return jsonify({"error": "Пользователь не найден"}), 401
  
  target_id = request.json.get("student_id")
  if target_id is None:
    return jsonify({"error": "Не указан ID ученика"}), 400
    
  try:
    target_id = int(target_id)
  except ValueError:
    return jsonify({"error": "Неверный формат ID"}), 400
    
  user_data["netschool_student_id"] = target_id
  # Fetch their name to update display if possible?
  # The next data reload will pull the right info anyway.
  _save_netschool_user_data(int(user_id), user_data)
  
  # Delete cache so it forces a refetch
  cache_path = _netschool_cache_path(int(user_id))
  try:
    if cache_path.exists():
      cache_path.unlink()
  except Exception:
    pass

  return jsonify({"ok": True, "message": "Ученик переключен"})

@app.route("/api/mini/netschool/settings/toggle", methods=["POST"])
def netschool_miniapp_toggle_setting():
  user_id = session.get("netschool_miniapp_user_id")
  if not user_id:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  payload = request.get_json(silent=True) or {}
  key = str(payload.get("key") or "").strip()
  value = payload.get("value")
  try:
    user_data, message = _toggle_netschool_setting(int(user_id), key, None if value is None else str(value))
    return jsonify({
      "profile": _build_netschool_miniapp_payload(user_data),
      "message": message,
    })
  except Exception as exc:
    return jsonify({"error": str(exc)}), 500

@app.route("/api/mini/netschool/child/select", methods=["POST"])
def netschool_miniapp_child_select():
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  payload = request.get_json(silent=True) or {}
  student_id_raw = payload.get("student_id")
  try:
    student_id = int(student_id_raw)
  except Exception:
    return jsonify({"error": "Некорректный идентификатор ребёнка"}), 400
  available = user_data.get("available_students") or []
  selected = next((item for item in available if int(item.get("id") or 0) == student_id), None)
  if not selected:
    return jsonify({"error": "Ребёнок не найден в профиле"}), 404
  user_data["selected_student_id"] = student_id
  user_data["student_name"] = str(selected.get("name") or user_data.get("student_name") or "").strip()
  user_data["updated_at"] = datetime.now().isoformat()
  _save_netschool_user_data(int(user_id), user_data)
  return jsonify({
    "ok": True,
    "profile": _build_netschool_miniapp_payload(user_data),
  })

@app.route("/api/mini/netschool/settings/icon", methods=["POST"])
def netschool_miniapp_save_icon():
  user_id = session.get("netschool_miniapp_user_id")
  if not user_id:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  user_data = _get_netschool_user_by_id(int(user_id))
  if not user_data:
    return jsonify({"error": "Профиль NetSchool не найден."}), 404
  payload = request.get_json(silent=True) or {}
  if payload.get("reset"):
    _delete_netschool_custom_icon(int(user_id))
    user_data.pop("pwa_icon_emoji", None)
    user_data.pop("pwa_icon_bg", None)
    user_data["pwa_icon_version"] = str(int(time.time()))
  else:
    image_data = str(payload.get("image_data") or "").strip()
    keep_image = bool(payload.get("keep_image"))
    if image_data:
      _store_netschool_custom_icon(int(user_id), image_data)
      # Add to gallery if public
      if payload.get("public", True):
        _add_icon_to_gallery(int(user_id))
    elif keep_image and _has_netschool_custom_icon(int(user_id)):
      user_data["pwa_icon_emoji"] = _sanitize_pwa_icon_emoji(payload.get("emoji"))
      user_data["pwa_icon_bg"] = _sanitize_pwa_icon_bg(payload.get("bg"))
    else:
      _delete_netschool_custom_icon(int(user_id))
      user_data["pwa_icon_emoji"] = _sanitize_pwa_icon_emoji(payload.get("emoji"))
      user_data["pwa_icon_bg"] = _sanitize_pwa_icon_bg(payload.get("bg"))
    user_data["pwa_icon_version"] = str(int(time.time()))
  user_data["updated_at"] = datetime.now().isoformat()
  _save_netschool_user_data(int(user_id), user_data)
  return jsonify({
    "ok": True,
    "profile": _build_netschool_miniapp_payload(user_data),
    "install_url": _issue_netschool_pwa_link(int(user_id), revoke_existing=False),
  })

@app.route("/api/mini/netschool/gallery")
def netschool_miniapp_gallery():
  user_id = session.get("netschool_miniapp_user_id")
  if not user_id:
    return jsonify({"error": "Не авторизован"}), 401
  icons = _list_gallery_icons()
  items = []
  for icon in icons:
    items.append({
      "id": icon["id"],
      "url": _external_url_for("netschool_miniapp_gallery_image", gallery_id=icon["id"]),
      "created_at": icon.get("created_at", ""),
      "owner_id": int(icon.get("user_id") or 0),
      "can_delete": int(icon.get("user_id") or 0) == int(user_id),
    })
  return jsonify({"icons": items})

@app.route("/api/mini/netschool/gallery/delete", methods=["POST"])
def netschool_miniapp_gallery_delete():
  user_id = session.get("netschool_miniapp_user_id")
  if not user_id:
    return jsonify({"error": "Не авторизован"}), 401
  payload = request.get_json(silent=True) or {}
  gallery_id = re.sub(r"[^a-zA-Z0-9_]", "", str(payload.get("id") or ""))
  owner_id = _get_gallery_icon_owner(gallery_id)
  if owner_id is None:
    return jsonify({"error": "Иконка не найдена"}), 404
  if int(owner_id) != int(user_id):
    return jsonify({"error": "Можно удалить только свою опубликованную иконку"}), 403
  if not _remove_gallery_icon(gallery_id):
    return jsonify({"error": "Иконка не найдена"}), 404
  return jsonify({"ok": True})

@app.route("/mini/netschool/gallery/<gallery_id>.png")
def netschool_miniapp_gallery_image(gallery_id):
  safe_id = re.sub(r"[^a-zA-Z0-9_]", "", str(gallery_id))
  gfile = NETSCHOOL_MINIAPP_GALLERY_DIR / f"{safe_id}.png"
  if not gfile.exists():
    return "Not found", 404
  response = make_response(gfile.read_bytes())
  response.headers["Content-Type"] = "image/png"
  response.headers["Cache-Control"] = "public, max-age=86400"
  return response

@app.route("/api/mini/netschool/gallery/select", methods=["POST"])
def netschool_miniapp_gallery_select():
  """Apply a gallery icon as user's PWA icon."""
  user_id = session.get("netschool_miniapp_user_id")
  if not user_id:
    return jsonify({"error": "Не авторизован"}), 401
  user_data = _get_netschool_user_by_id(int(user_id))
  if not user_data:
    return jsonify({"error": "Профиль не найден"}), 404
  payload = request.get_json(silent=True) or {}
  gallery_id = re.sub(r"[^a-zA-Z0-9_]", "", str(payload.get("id") or ""))
  gfile = NETSCHOOL_MINIAPP_GALLERY_DIR / f"{gallery_id}.png"
  if not gfile.exists():
    return jsonify({"error": "Иконка не найдена"}), 404
  import shutil
  NETSCHOOL_MINIAPP_ICONS_DIR.mkdir(parents=True, exist_ok=True)
  dst = _netschool_miniapp_icon_file(int(user_id))
  shutil.copy2(str(gfile), str(dst))
  user_data["pwa_icon_version"] = str(int(time.time()))
  user_data["updated_at"] = datetime.now().isoformat()
  _save_netschool_user_data(int(user_id), user_data)
  return jsonify({
    "ok": True,
    "profile": _build_netschool_miniapp_payload(user_data),
    "install_url": _issue_netschool_pwa_link(int(user_id), revoke_existing=False),
  })

@app.route("/api/mini/netschool/feedback", methods=["POST"])
def netschool_miniapp_feedback():
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  payload = request.get_json(silent=True) or {}
  kind = str(payload.get("kind") or "bug").strip().lower()
  if kind not in {"bug", "feature"}:
    kind = "bug"
  subject = str(payload.get("subject") or "").strip()
  message = str(payload.get("message") or "").strip()
  if len(subject) < 4:
    return jsonify({"error": "Добавьте короткий заголовок"}), 400
  if len(message) < 10:
    return jsonify({"error": "Опишите проблему или идею подробнее"}), 400
  entry = {
    "created_at": datetime.now().isoformat(),
    "kind": kind,
    "subject": subject[:140],
    "message": message[:4000],
    "current_tab": str(payload.get("current_tab") or "").strip()[:40],
    "page_url": str(payload.get("page_url") or "").strip()[:500],
    "standalone": bool(payload.get("standalone")),
    "user_agent": str(request.headers.get("User-Agent") or "")[:500],
    "remote_addr": str(request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:200],
    "user": {
      "id": int(user_id),
      "login": str(user_data.get("login") or "")[:120],
      "student_name": str(user_data.get("student_name") or "")[:200],
      "school": str(user_data.get("school") or "")[:200],
    },
  }
  try:
    _append_netschool_feedback(entry)
    telegram_sent = _send_netschool_feedback_to_telegram(entry)
    return jsonify({"ok": True, "telegram_sent": telegram_sent})
  except Exception as exc:
    return jsonify({"error": str(exc)}), 500

@app.route("/api/mini/netschool/session/request-code", methods=["POST"])
def netschool_miniapp_request_session_code():
  """Request a one-time code sent to Telegram to recover expired session."""
  payload = request.get_json(silent=True) or {}
  token = str(payload.get("token") or "").strip() or _extract_netschool_miniapp_token()
  if not token:
    return jsonify({"error": "Токен не найден"}), 400
  user_id_str = _validate_netschool_miniapp_token(token)
  if not user_id_str:
    if _request_invalid_token_recovery(token):
      return jsonify({
        "ok": True,
        "recovery_requested": True,
        "message": "Запрос отправлен в Telegram предыдущему владельцу ссылки. Там можно отклонить вход или получить код."
      }), 202
    return jsonify({"error": "Токен недействителен или истёк. Получите новый токен через бота."}), 403
  user_id = int(user_id_str)
  user_data = _get_netschool_user_by_id(user_id)
  if not user_data:
    return jsonify({"error": "Профиль не найден"}), 404
  code = _issue_session_code(user_id)
  # Send code to Telegram via log_bot or main bot
  _send_session_code_to_telegram(user_id, code)
  return jsonify({"ok": True, "message": "Код отправлен в Telegram"})

@app.route("/api/mini/netschool/session/verify-code", methods=["POST"])
def netschool_miniapp_verify_session_code():
  """Verify a one-time code to restore session."""
  payload = request.get_json(silent=True) or {}
  code = str(payload.get("code") or "").strip()
  if not code or len(code) != 6:
    return jsonify({"error": "Введите 6-значный код"}), 400
  user_id = _verify_session_code(code)
  if not user_id:
    return jsonify({"error": "Неверный или просроченный код"}), 403
  user_data = _get_netschool_user_by_id(user_id)
  if not user_data:
    return jsonify({"error": "Профиль не найден"}), 404
  # Restore session
  session.permanent = True
  session["netschool_miniapp_user_id"] = str(user_id)
  token = _find_existing_netschool_miniapp_token(user_id)
  if token:
    session["netschool_miniapp_token"] = token
  return jsonify({"ok": True, "profile": _build_netschool_miniapp_payload(user_data)})

def _send_session_code_to_telegram(user_id: int, code: str) -> None:
  """Send session recovery code to user via Telegram."""
  import urllib.request
  bot_token = (
    os.getenv("NETSCHOOL_BOT_TOKEN")
    or os.getenv("TG_BOT_TOKEN")
    or os.getenv("BOT_TOKEN")
    or os.getenv("LOG_BOT_TOKEN")
    or ""
  )
  if not bot_token:
    return
  text = f"🔐 Код для входа в PWA: <b>{code}</b>\n\nДействует 5 минут. Не передавайте никому."
  payload_data = json.dumps({"chat_id": user_id, "text": text, "parse_mode": "HTML"}).encode()
  req = urllib.request.Request(
    f"https://api.telegram.org/bot{bot_token}/sendMessage",
    data=payload_data,
    headers={"Content-Type": "application/json"},
  )
  try:
    urllib.request.urlopen(req, timeout=10)
  except Exception:
    pass

@app.route("/api/mini/netschool/dashboard")
def netschool_miniapp_dashboard():
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401

  # Cache-first: serve recent data from our server, then refresh from SGO when cache is stale.
  cache_entry = _load_netschool_miniapp_cache_entry(int(user_id), "dashboard")
  if _is_cache_entry_fresh(cache_entry):
    cached_payload = dict((cache_entry or {}).get("payload") or {})
    if cached_payload:
      cached_payload["is_cached"] = True
      cached_payload.setdefault("cache_notice", "Показаны сохраненные данные с нашего сервера.")
      cached_payload.setdefault("profile", _build_netschool_appearance_payload(user_data))
      response = jsonify(cached_payload)
      response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
      response.headers["Pragma"] = "no-cache"
      return response

  try:
    payload = _run_async(_fetch_diary_bundle_live(int(user_id), user_data))
    user_data["last_sync_at"] = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
    user_data["updated_at"] = datetime.now().isoformat()
    _save_netschool_user_data(int(user_id), user_data)
    payload["is_cached"] = False
    payload["profile"] = _build_netschool_appearance_payload(user_data)
    _save_netschool_miniapp_cache_section(int(user_id), "dashboard", payload)
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response
  except Exception as exc:
    import traceback
    traceback.print_exc()
    payload, status, should_recover = _classify_netschool_exception(exc)
    if should_recover:
      session.pop("netschool_miniapp_user_id", None)
      return jsonify(payload), status
    cached = _load_netschool_miniapp_cache_section(int(user_id), "dashboard")
    if cached:
      cached_payload = dict(cached)
      cached_payload["is_cached"] = True
      cached_payload["cache_notice"] = "Нет связи с NetSchool. Показаны последние сохраненные данные."
      cached_payload.setdefault("profile", _build_netschool_appearance_payload(user_data))
      response = jsonify(cached_payload)
      response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
      response.headers["Pragma"] = "no-cache"
      return response
    return jsonify(payload), status

@app.route("/api/mini/netschool/totals")
def mini_netschool_totals():
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401

  cache_entry = _load_netschool_miniapp_cache_entry(int(user_id), "totals")
  if _is_cache_entry_fresh(cache_entry):
    cached_payload = dict((cache_entry or {}).get("payload") or {})
    if cached_payload:
      response = jsonify(cached_payload)
      response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
      response.headers["Pragma"] = "no-cache"
      return response

  try:
    async def _load_totals(client):
      return await _fetch_student_total_marks_report(client)

    marks = _run_async(_run_netschool_request(int(user_id), user_data, _load_totals))
    totals_payload = {"totals": _normalize_total_marks_rows(marks), "fallback": False}
    _save_netschool_miniapp_cache_section(int(user_id), "totals", totals_payload)
    response = jsonify(totals_payload)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response
  except Exception as e:
    payload, status, should_recover = _classify_netschool_exception(e)
    if should_recover:
      session.pop("netschool_miniapp_user_id", None)
      return jsonify(payload), status
    # Fallback: rebuild quarter finals from diary data when totals endpoint is unavailable.
    err_text = str(e)
    if (
      "не поддерживает официальный отчёт" in err_text
      or "StudentTotalMarks" in err_text
      or "официального отчёта" in err_text
      or "queue" in err_text.lower()
      or "signalr" in err_text.lower()
      or "websocket" in err_text.lower()
    ):
      try:
        payload = _run_async(_fetch_diary_bundle_live(int(user_id), user_data))
        quarter_cols = payload.get("quarter_columns") or []
        subjects = payload.get("subjects") or []
        fallback = []
        for subject in subjects:
          q_marks = []
          quarters = subject.get("quarters") or {}
          for col in quarter_cols:
            key = col.get("key")
            q_data = quarters.get(key) or {}
            est = q_data.get("estimated_final_grade")
            if not est:
              avg = q_data.get("average")
              if avg is not None:
                try:
                  est = str(math.floor(float(avg) + 0.5))
                except Exception:
                  est = None
            q_marks.append(est or "-")
          while q_marks and q_marks[-1] == "-":
            q_marks.pop()
          fallback.append({
            "subject": subject.get("subject") or "—",
            "period_marks": q_marks or ["-"],
            "year_mark": None,
            "exam_mark": None,
            "final_mark": None,
          })
        fallback_payload = {
          "totals": fallback,
          "fallback": True,
          "notice": "Официальный отчёт в вашей школе не поддерживается, показан расчёт по дневнику.",
        }
        _save_netschool_miniapp_cache_section(int(user_id), "totals", fallback_payload)
        response = jsonify(fallback_payload)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response
      except Exception as fallback_exc:
        return _netschool_error_response(fallback_exc, clear_miniapp_session=False)
    return jsonify(payload), status

@app.route("/api/mini/netschool/grades")
def netschool_miniapp_grades():
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  try:
    payload = _run_async(_fetch_diary_bundle_live(int(user_id), user_data))
    return jsonify({"subjects": payload.get("subjects", [])})
  except Exception as exc:
    return _netschool_error_response(exc)

@app.route("/api/mini/netschool/mail")
def netschool_miniapp_mail():
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  page = request.args.get("page", type=int) or 1
  page_size = request.args.get("page_size", type=int) or 20
  try:
    payload = _run_async(_fetch_mail_list_live(int(user_id), user_data, page=page, page_size=page_size))
    if page == 1:
      _save_netschool_miniapp_cache_section(int(user_id), "mail_list", payload)
    return jsonify(payload)
  except Exception as exc:
    cached = _load_netschool_miniapp_cache_section(int(user_id), "mail_list")
    if cached:
      return jsonify(cached)
    return _netschool_error_response(exc)

@app.route("/api/mini/netschool/homework-detail")
def netschool_miniapp_homework_detail():
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  raw_date = str(request.args.get("date") or "").strip()
  lesson_index = request.args.get("lesson", type=int)
  if not raw_date or lesson_index is None:
    return jsonify({"error": "Не хватает параметров задания"}), 400
  try:
    target_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
  except ValueError:
    return jsonify({"error": "Некорректная дата задания"}), 400
  cache_key = f"hw_detail_{raw_date}_{lesson_index}"
  try:
    payload = _run_async(_fetch_homework_detail_live(int(user_id), user_data, target_date, int(lesson_index)))
    _save_netschool_miniapp_cache_section(int(user_id), cache_key, payload)
    return jsonify(payload)
  except Exception as exc:
    cached = _load_netschool_miniapp_cache_section(int(user_id), cache_key)
    if cached:
      return jsonify(cached)
    return _netschool_error_response(exc)

@app.route("/api/mini/netschool/mail/<int:message_id>")
def netschool_miniapp_mail_read(message_id: int):
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  try:
    payload = _run_async(_fetch_mail_message_live(int(user_id), user_data, message_id))
    _save_netschool_miniapp_cache_section(int(user_id), f"mail_message_{message_id}", payload)
    return jsonify(payload)
  except Exception as exc:
    cached = _load_netschool_miniapp_cache_section(int(user_id), f"mail_message_{message_id}")
    if cached:
      return jsonify(cached)
    return jsonify({"error": str(exc)}), 500

@app.route("/api/mini/netschool/mail/read-all", methods=["POST"])
def netschool_miniapp_mail_read_all():
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  payload = request.get_json(silent=True) or {}
  ids = payload.get("ids") or []
  try:
    normalized_ids = _normalize_mail_seen_ids(ids or [])

    async def _load_unread_ids(client):
      unread = await client.mail_unread()
      return _normalize_mail_seen_ids(unread or [], limit=5000)

    unread_ids = _run_async(_run_netschool_request(int(user_id), user_data, _load_unread_ids))
    seen = set(_normalize_mail_seen_ids(user_data.get("mail_seen_ids") or []))
    before = len(seen)
    seen.update(normalized_ids)
    seen.update(unread_ids)
    user_data["mail_seen_ids"] = sorted(seen, reverse=True)[:500]
    user_data["mail_unread_count"] = 0
    user_data["updated_at"] = datetime.now().isoformat()
    _save_netschool_user_data(int(user_id), user_data)
    return jsonify({"ok": True, "count": max(0, len(seen) - before)})
  except Exception as exc:
    return jsonify({"error": str(exc)}), 500

@app.route("/mini/netschool/manifest.webmanifest")
def netschool_miniapp_manifest():
  user_data = _get_netschool_miniapp_user_for_request() or {}
  start_url = _external_url_for("netschool_miniapp_page")
  session_token = _get_current_netschool_miniapp_token()
  if session_token:
    start_url = f"{start_url}?token={quote(session_token)}"
  icon_url = _netschool_miniapp_icon_url(user_data)
  icon_type = "image/png" if _has_netschool_custom_icon(user_data.get("user_id")) else "image/svg+xml"
  manifest = {
    "name": "NetSchool Дневник",
    "short_name": "NetSchool",
    "start_url": start_url,
    "scope": _external_url_for("netschool_miniapp_page").rsplit("/mini/netschool", 1)[0] + "/mini/",
    "display": "standalone",
    "background_color": "#eef3f8",
    "theme_color": "#2f5fa8",
    "icons": [
      {
        "src": icon_url,
        "sizes": "512x512",
        "type": icon_type,
        "purpose": "any maskable",
      }
    ],
  }
  response = jsonify(manifest)
  response.mimetype = "application/manifest+json"
  return response

@app.route("/mini/netschool/icon")
@app.route("/mini/netschool/icon.svg")
def netschool_miniapp_icon():
  user_data = _get_netschool_miniapp_user_for_request() or {}
  user_id = user_data.get("user_id")
  if user_id and _has_netschool_custom_icon(user_id):
    response = send_file(_netschool_miniapp_icon_file(user_id), mimetype="image/png", max_age=0)
    response.headers["Cache-Control"] = "no-store"
    return response
  icon_emoji = html.escape(_sanitize_pwa_icon_emoji(user_data.get("pwa_icon_emoji")))
  icon_bg = _sanitize_pwa_icon_bg(user_data.get("pwa_icon_bg"))
  svg = f"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'>
  <defs>
    <linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>
      <stop offset='0%' stop-color='{icon_bg}'/>
      <stop offset='100%' stop-color='#203d67'/>
    </linearGradient>
  </defs>
  <rect width='512' height='512' rx='118' fill='url(#g)'/>
  <circle cx='406' cy='106' r='52' fill='rgba(255,255,255,.14)'/>
  <rect x='96' y='98' width='320' height='316' rx='44' fill='rgba(255,255,255,.16)'/>
  <text x='256' y='286' text-anchor='middle' font-size='180'>{icon_emoji}</text>
  </svg>"""
  response = make_response(svg)
  response.mimetype = "image/svg+xml"
  response.headers["Cache-Control"] = "no-store"
  return response

@app.route("/mini/netschool/sw.js")
def netschool_miniapp_service_worker():
  script = """
self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  const payload = event.data ? event.data.json() : {};
  event.waitUntil(self.registration.showNotification(payload.title || 'NetSchool', {
    body: payload.body || '',
    icon: payload.icon || '/mini/netschool/icon.svg',
    badge: payload.badge || '/mini/netschool/icon.svg',
    tag: payload.tag || 'netschool',
    data: {
      url: payload.url || '/mini/netschool',
      ...(payload.data || {}),
    },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/mini/netschool';
  event.waitUntil((async () => {
    const allClients = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of allClients) {
      if ('focus' in client) {
        await client.navigate(url);
        return client.focus();
      }
    }
    if (clients.openWindow) {
      return clients.openWindow(url);
    }
  })());
});
""".strip()
  response = make_response(script)
  response.mimetype = "application/javascript"
  response.headers["Service-Worker-Allowed"] = "/mini/"
  response.headers["Cache-Control"] = "no-cache"
  return response

@app.route("/api/mini/netschool/mail/<int:message_id>/attachments/<int:attachment_id>")
def netschool_miniapp_mail_attachment(message_id: int, attachment_id: int):
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  try:
    buffer, filename = _run_async(_download_mail_attachment_live(int(user_id), user_data, message_id, attachment_id))
    download_name = request.args.get("name") or filename
    mimetype, _ = mimetypes.guess_type(download_name)
    inline = request.args.get("inline") == "1"
    response = send_file(buffer, as_attachment=not inline, download_name=download_name, mimetype=mimetype or "application/octet-stream")
    if request.args.get("open_external") == "1":
      response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
      response.headers["Pragma"] = "no-cache"
      response.headers["X-Frame-Options"] = "ALLOWALL"
    return response
  except Exception as exc:
    return _netschool_error_response(exc)

@app.route("/api/mini/netschool/attachments/<int:attachment_id>")
def netschool_miniapp_download_attachment(attachment_id: int):
  """Download any NetSchool attachment by ID (homework files, etc.)."""
  user_id = session.get("netschool_miniapp_user_id")
  user_data = _get_netschool_miniapp_user()
  if not user_id or not user_data:
    session.pop("netschool_miniapp_user_id", None)
    return jsonify({"error": "Сессия мини-приложения недействительна или истекла"}), 401
  try:
    async def _download(client):
        buf = io.BytesIO()
        await client.download_attachment(attachment_id, buf, timeout=90)
        buf.seek(0)
        return buf
    buffer = _run_async(_run_netschool_request(int(user_id), user_data, _download))
    fname = request.args.get("name", f"attachment_{attachment_id}")
    mimetype, _ = mimetypes.guess_type(fname)
    inline = request.args.get("inline") == "1"
    response = send_file(buffer, as_attachment=not inline, download_name=fname, mimetype=mimetype or "application/octet-stream")
    if request.args.get("open_external") == "1":
      response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
      response.headers["Pragma"] = "no-cache"
      response.headers["X-Frame-Options"] = "ALLOWALL"
    return response
  except Exception as exc:
    return _netschool_error_response(exc)

