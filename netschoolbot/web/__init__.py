"""Веб-часть NetSchool-бота: панель управления и PWA мини-приложение."""

from .app import app, socketio  # noqa: F401

# Импорт ради регистрации маршрутов и socket.io-обработчиков.
from . import files, miniapp, terminal  # noqa: E402,F401


def run_web() -> None:
    """Запуск веб-сервера (блокирующий)."""
    from ..config import WEB_PORT

    socketio.run(app, host="0.0.0.0", port=WEB_PORT, allow_unsafe_werkzeug=True)
