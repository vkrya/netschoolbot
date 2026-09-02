"""Flask-приложение: авторизация в панели, статика, точка входа веб-сервера."""

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, jsonify, make_response, redirect, render_template_string,
    request, send_file, session, url_for,
)
from flask_socketio import SocketIO, disconnect, emit
from werkzeug.middleware.proxy_fix import ProxyFix

from ..config import (
    WEB_AUTH_FILE as AUTH_FILE,
    WEB_COOKIE_SAMESITE as WEBTERM_COOKIE_SAMESITE,
    WEB_FILE_ROOT as FILE_ROOT,
    WEB_JOURNAL_TAIL as JOURNAL_TAIL,
    WEB_PASS as WEBTERM_PASS,
    WEB_PORT as WEBTERM_PORT,
    WEB_SECRET as WEBTERM_SECRET,
    WEB_SECURE_COOKIE as WEBTERM_SECURE_COOKIE,
    WEB_SESSION_HOURS as WEBTERM_SESSION_HOURS,
    WEB_STATIC_DIR as STATIC_DIR,
    WEB_USER as WEBTERM_USER,
)
from .templates import LOGIN_HTML, MAIN_HTML

logger = logging.getLogger("netschoolbot.web")

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = WEBTERM_SECRET
STATIC_VERSION = str(int(time.time()))
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(hours=WEBTERM_SESSION_HOURS),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=WEBTERM_SECURE_COOKIE,
    SESSION_COOKIE_SAMESITE=WEBTERM_COOKIE_SAMESITE,
    SESSION_REFRESH_EACH_REQUEST=True,
)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False,
)

# sid -> {"fd": int, "pid": int, "thread": Thread}
_pty_sessions: dict = {}


# ── Static assets (self-hosted, no CDN dependency) ───────────
def _external_url_for(endpoint: str, **values) -> str:
  path = url_for(endpoint, **values)
  forwarded_prefix = (request.headers.get("X-Forwarded-Prefix") or "").rstrip("/")
  if forwarded_prefix and path.startswith("/") and not path.startswith(forwarded_prefix):
    return f"{forwarded_prefix}{path}"
  return path

def _absolute_external_url_for(endpoint: str, **values) -> str:
  path = _external_url_for(endpoint, **values)
  if path.startswith("http://") or path.startswith("https://"):
    return path
  scheme = (request.headers.get("X-Forwarded-Proto") or request.scheme or "https").split(",", 1)[0].strip()
  host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",", 1)[0].strip()
  if not host:
    return path
  return f"{scheme}://{host}{path}"


@app.route("/static_web/<path:filename>")
def static_assets(filename):
    filepath = STATIC_DIR / filename
    if not filepath.exists() or not filepath.is_file():
        abort(404)
    return send_file(str(filepath))

# ── Auth ──────────────────────────────────────────────────────
LOGIN_ATTEMPTS: dict = {}  # ip -> [timestamps]

def _hash_password(password: str, salt: bytes, iterations: int = 200_000) -> str:
  digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
  return f"{iterations}${salt.hex()}${digest.hex()}"

def _verify_password(stored: str, password: str) -> bool:
  try:
    iterations_str, salt_hex, digest_hex = stored.split("$", 2)
    iterations = int(iterations_str)
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(expected, actual)
  except Exception:
    return False

def _load_auth_hash() -> str | None:
  if not AUTH_FILE.exists():
    return None
  try:
    data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    return data.get("password_hash")
  except Exception:
    return None

def _save_auth_hash(password: str) -> None:
  salt = secrets.token_bytes(16)
  AUTH_FILE.write_text(
    json.dumps({"password_hash": _hash_password(password, salt)}, ensure_ascii=False, indent=2),
    encoding="utf-8",
  )

def _check_login_rate(ip: str) -> bool:
  now = time.time()
  attempts = [t for t in LOGIN_ATTEMPTS.get(ip, []) if now - t < 300]
  LOGIN_ATTEMPTS[ip] = attempts
  return len(attempts) < 5

def _record_login_attempt(ip: str) -> None:
  now = time.time()
  attempts = [t for t in LOGIN_ATTEMPTS.get(ip, []) if now - t < 300]
  attempts.append(now)
  LOGIN_ATTEMPTS[ip] = attempts

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(_external_url_for("login_page"))
        return f(*args, **kwargs)
    return decorated

@app.route("/")
@login_required
def index():
  return render_template_string(MAIN_HTML, static_version=STATIC_VERSION)

@app.route("/login", methods=["GET", "POST"])
def login_page():
  error = None
  if request.method == "POST":
    ip = request.headers.get("X-Real-IP", request.remote_addr or "")
    if not _check_login_rate(ip):
      error = "Слишком много попыток. Подождите 5 минут."
      return render_template_string(LOGIN_HTML, error=error)
    user_ok = request.form.get("username") == WEBTERM_USER
    pass_raw = request.form.get("password") or ""
    stored_hash = _load_auth_hash()
    pass_ok = _verify_password(stored_hash, pass_raw) if stored_hash else (pass_raw == WEBTERM_PASS)
    if user_ok and pass_ok:
      session.permanent = True
      session["logged_in"] = True
      return redirect(_external_url_for("index"))
    _record_login_attempt(ip)
    error = "Неверный логин или пароль"
  return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
  session.clear()
  return redirect(_external_url_for("login_page"))

@app.route("/api/auth/change_password", methods=["POST"])
def change_password():
  _check_auth()
  try:
    data = request.get_json()
    current = data.get("current", "")
    new_password = data.get("new_password", "")
    if len(new_password) < 8:
      return jsonify({"error": "Пароль должен быть минимум 8 символов"})
    stored_hash = _load_auth_hash()
    if stored_hash:
      if not _verify_password(stored_hash, current):
        return jsonify({"error": "Текущий пароль неверный"})
    elif current != WEBTERM_PASS:
      return jsonify({"error": "Текущий пароль неверный"})
    _save_auth_hash(new_password)
    return jsonify({"ok": True})
  except Exception as e:
    return jsonify({"error": str(e)})

def _safe_path(path: str) -> Path:
    """Resolve path within FILE_ROOT (jail)."""
    try:
        p = (FILE_ROOT / path.lstrip("/")).resolve()
    except Exception:
        raise ValueError("Неверный путь")
    return p

def _check_auth():
    if not session.get("logged_in"):
        abort(401)

def _load_json_file(path: Path, default):
  if not path.exists():
    return default
  try:
    return json.loads(path.read_text(encoding="utf-8"))
  except Exception:
    return default

