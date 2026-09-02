"""Маршруты панели управления (терминал, файловый менеджер, вход).

Панель включается только флагом NETSCHOOL_PANEL_ENABLED. На боевом домене
netschool.ikrya.ru она выключена: администрирование сервера живёт в отдельной
панели на vdsru.ikrya.ru, а здесь публикуется только мини-приложение.
"""

from flask import redirect, render_template_string, request, jsonify, session

from .app import (
    STATIC_VERSION,
    WEBTERM_PASS,
    WEBTERM_USER,
    _check_auth,
    _check_login_rate,
    _external_url_for,
    _load_auth_hash,
    _record_login_attempt,
    _save_auth_hash,
    _verify_password,
    app,
    login_required,
)
from .templates import LOGIN_HTML, MAIN_HTML


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
