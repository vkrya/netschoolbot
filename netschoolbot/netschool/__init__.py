"""Работа с «Сетевым городом»."""

from . import esia_patch, http_patch

# Правки HTTP-слоя netschoolpy применяем до первых запросов.
http_patch.apply()
# Правки ЕСИА-входа (202 на проверке кода, MAX_QUIZ).
esia_patch.apply()
