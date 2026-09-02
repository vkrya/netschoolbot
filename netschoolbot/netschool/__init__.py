"""Работа с «Сетевым городом»."""

from . import http_patch

# Правки HTTP-слоя netschoolpy применяем до первых запросов.
http_patch.apply()
