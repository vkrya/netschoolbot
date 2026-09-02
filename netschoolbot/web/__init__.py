"""Веб-часть NetSchool-бота.

По умолчанию публикуется только PWA мини-приложение. Панель управления
сервером (терминал, файловый менеджер, управление службами) подключается
лишь при NETSCHOOL_PANEL_ENABLED=true — на боевом домене администрирование
вынесено в отдельную панель на vdsru.ikrya.ru.
"""

from ..config import PANEL_ENABLED
from .app import app, register_root_redirect, socketio  # noqa: F401

# Импорт ради регистрации маршрутов и socket.io-обработчиков.
from . import miniapp  # noqa: E402,F401

if PANEL_ENABLED:
    from . import files, panel, terminal  # noqa: E402,F401
else:
    register_root_redirect()


def run_web() -> None:
    """Запуск веб-сервера (блокирующий)."""
    from ..config import WEB_PORT

    socketio.run(app, host="0.0.0.0", port=WEB_PORT, allow_unsafe_werkzeug=True)
