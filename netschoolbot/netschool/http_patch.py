"""Правки поведения HTTP-слоя netschoolpy.

Библиотека при первой же неудаче прямого соединения (таймаут по умолчанию —
5 секунд) помечает хост в глобальном `_tor_hosts` и **до конца жизни процесса**
гонит все запросы к нему через Tor (socks5://127.0.0.1:9050). Если Tor мёртв
или заблокирован, бот получает «Сервер не ответил (Tor)» даже тогда, когда
прямое соединение прекрасно работает — именно так ломался поиск школ.

Здесь мы, не трогая саму библиотеку:
  * поднимаем таймаут прямого соединения (медленный ответ ≠ недоступный сервер);
  * переводим fallback с Tor на рабочий SOCKS5 (xray), если он поднят;
  * даём пометке «хост требует прокси» срок жизни, чтобы одна неудача
    не выключала прямые запросы навсегда.
"""

import logging
import os
import socket
import time
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("netschoolbot")

# Таймаут прямого соединения: netschoolpy по умолчанию даёт всего 5 секунд
HTTP_TIMEOUT = max(5, int(os.getenv("NETSCHOOL_HTTP_TIMEOUT", "20")))
# Сколько держать пометку «к этому хосту нужен прокси»
BLOCKED_HOST_TTL = max(60, int(os.getenv("NETSCHOOL_BLOCKED_HOST_TTL", "600")))
# Прокси для fallback: пусто — автоопределение локального xray, "off" — оставить Tor
FALLBACK_PROXY = (os.getenv("NETSCHOOL_FALLBACK_PROXY") or "").strip()
DEFAULT_FALLBACK_CANDIDATES = ("socks5://127.0.0.1:1080",)

_applied = False


class _ExpiringHostSet(set):
    """Множество хостов с TTL: пометка о недоступности сама протухает."""

    def __init__(self, ttl: int = BLOCKED_HOST_TTL):
        super().__init__()
        self._ttl = ttl
        self._added: dict[str, float] = {}

    def add(self, item) -> None:
        self._added[item] = time.monotonic()
        super().add(item)

    def discard(self, item) -> None:
        self._added.pop(item, None)
        super().discard(item)

    def __contains__(self, item) -> bool:
        added_at = self._added.get(item)
        if added_at is not None and time.monotonic() - added_at > self._ttl:
            self.discard(item)
            logger.info(f"🔁 Снята пометка «нужен прокси» с {item}, пробуем напрямую")
            return False
        return super().__contains__(item)


def _proxy_reachable(proxy_url: str, timeout: float = 0.7) -> bool:
    parsed = urlparse(proxy_url)
    host, port = parsed.hostname, parsed.port
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_fallback_proxy() -> Optional[str]:
    """Рабочий SOCKS5 для замены Tor, либо None."""
    if FALLBACK_PROXY.lower() in {"off", "none", "no"}:
        return None
    candidates = [FALLBACK_PROXY] if FALLBACK_PROXY else list(DEFAULT_FALLBACK_CANDIDATES)
    for candidate in candidates:
        if candidate and _proxy_reachable(candidate):
            return candidate
    return None


def reset_blocked_hosts() -> None:
    """Сбросить накопленные пометки о «заблокированных» хостах."""
    try:
        import netschoolpy.http as ns_http

        ns_http._tor_hosts.clear()
    except Exception:
        pass


def apply() -> None:
    """Применить правки. Безопасно вызывать несколько раз."""
    global _applied
    if _applied:
        return
    try:
        import netschoolpy.http as ns_http
    except Exception as exc:  # pragma: no cover
        logger.warning(f"Не удалось пропатчить netschoolpy.http: {exc}")
        return

    ns_http._DEFAULT_TIMEOUT = HTTP_TIMEOUT
    ns_http._tor_hosts = _ExpiringHostSet(BLOCKED_HOST_TTL)

    proxy = resolve_fallback_proxy()
    if proxy:
        ns_http._TOR_PROXY = proxy
        logger.info(f"🌐 Fallback для «Сетевого города»: {proxy} (вместо Tor)")
    else:
        logger.info("🧅 Рабочий SOCKS5 не найден, fallback остаётся на Tor")

    logger.info(
        f"⏱ Таймаут прямых запросов к «Сетевому городу»: {HTTP_TIMEOUT}с, "
        f"пометка о недоступности живёт {BLOCKED_HOST_TTL}с"
    )
    _applied = True
