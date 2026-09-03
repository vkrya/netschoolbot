"""Правки HTTP-слоя netschoolpy.

Перенесено из старого `netschool/http_patch.py` — это выстраданное знание о
поведении чужой библиотеки, переписывать его с нуля было бы вредительством.

Суть проблемы: netschoolpy при первой же неудаче прямого соединения (таймаут
по умолчанию — 5 секунд) помечает хост в глобальном `_tor_hosts` и до конца
жизни процесса гонит все запросы к нему через Tor. Если Tor мёртв или
заблокирован, бот получает «Сервер не ответил (Tor)» даже тогда, когда прямое
соединение прекрасно работает — именно так ломался поиск школ.

Не трогая саму библиотеку:
  * поднимаем таймаут прямого соединения (медленный ответ ≠ недоступный хост);
  * переводим fallback с Tor на рабочий SOCKS5, если он поднят;
  * даём пометке «хост требует прокси» срок жизни, чтобы одна неудача не
    выключала прямые запросы навсегда.
"""

from __future__ import annotations

import logging
import socket
import time
from urllib.parse import urlparse

logger = logging.getLogger("netschoolbot.netschool")

DEFAULT_FALLBACK_CANDIDATES = ("socks5://127.0.0.1:1080",)

_applied = False


class ExpiringHostSet(set):
    """Множество хостов с TTL: пометка о недоступности сама протухает."""

    def __init__(self, ttl: int) -> None:
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
            logger.info("Снята пометка «нужен прокси» с %s, пробуем напрямую", item)
            return False
        return super().__contains__(item)


def _proxy_reachable(proxy_url: str, timeout: float = 0.7) -> bool:
    parsed = urlparse(proxy_url)
    if not parsed.hostname or not parsed.port:
        return False
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_fallback_proxy(configured: str = "") -> str | None:
    """Рабочий SOCKS5 для замены Tor, либо None."""
    if configured.lower() in {"off", "none", "no"}:
        return None
    candidates = [configured] if configured else list(DEFAULT_FALLBACK_CANDIDATES)
    return next((c for c in candidates if c and _proxy_reachable(c)), None)


def reset_blocked_hosts() -> None:
    """Сбросить накопленные пометки о «заблокированных» хостах."""
    try:
        import netschoolpy.http as ns_http
    except ImportError:
        return
    ns_http._tor_hosts.clear()


def apply(*, timeout: int, blocked_host_ttl: int, fallback_proxy: str = "") -> None:
    """Применить правки. Безопасно вызывать несколько раз."""
    global _applied
    if _applied:
        return
    try:
        import netschoolpy.http as ns_http
    except ImportError as exc:
        logger.warning("netschoolpy.http недоступен, правки не применены: %s", exc)
        return

    ns_http._DEFAULT_TIMEOUT = timeout
    ns_http._tor_hosts = ExpiringHostSet(blocked_host_ttl)

    proxy = resolve_fallback_proxy(fallback_proxy)
    if proxy:
        ns_http._TOR_PROXY = proxy
        logger.info("Fallback для «Сетевого города»: %s (вместо Tor)", proxy)
    else:
        logger.info("Рабочий SOCKS5 не найден, fallback остаётся на Tor")

    logger.info(
        "Таймаут прямых запросов: %sс, пометка о недоступности живёт %sс",
        timeout,
        blocked_host_ttl,
    )
    _applied = True
