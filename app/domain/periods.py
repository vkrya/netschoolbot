"""Учебные четверти.

Границы четвертей «Сетевой город» не отдаёт: они у каждой школы свои и
меняются год от года. Здесь взяты общепринятые для российской школы даты —
их достаточно, чтобы разложить оценки по четвертям и посчитать средний балл.

Вынесено отдельным модулем без зависимостей, потому что это единственная
часть логики, где приходится угадывать: её нужно уметь проверять и менять,
не задевая остальное.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

# (ключ, подпись, месяц и день начала). Учебный год начинается 1 сентября.
QUARTER_BOUNDS = (
    ("q1", "1 четверть", (9, 1)),
    ("q2", "2 четверть", (11, 1)),
    ("q3", "3 четверть", (1, 9)),
    ("q4", "4 четверть", (4, 1)),
)

QUARTER_KEYS = tuple(key for key, _, _ in QUARTER_BOUNDS)
QUARTER_LABELS = {key: label for key, label, _ in QUARTER_BOUNDS}


@dataclass(frozen=True, slots=True)
class Quarter:
    key: str
    label: str
    start: dt.date
    end: dt.date

    def covers(self, day: dt.date) -> bool:
        return self.start <= day <= self.end


def academic_year_start(today: dt.date) -> int:
    """Год, в котором начался текущий учебный год.

    До сентября мы всё ещё в учебном году, начавшемся прошлой осенью.
    """
    return today.year if today.month >= 9 else today.year - 1


def quarters(today: dt.date) -> list[Quarter]:
    """Четверти учебного года, к которому относится указанный день."""
    year = academic_year_start(today)
    starts: list[tuple[str, str, dt.date]] = []
    for key, label, (month, day) in QUARTER_BOUNDS:
        # Январь и апрель — это уже следующий календарный год.
        calendar_year = year if month >= 9 else year + 1
        starts.append((key, label, dt.date(calendar_year, month, day)))

    result: list[Quarter] = []
    for index, (key, label, start) in enumerate(starts):
        if index + 1 < len(starts):
            end = starts[index + 1][2] - dt.timedelta(days=1)
        else:
            # Последняя четверть длится до конца учебного года.
            end = dt.date(year + 1, 8, 31)
        result.append(Quarter(key=key, label=label, start=start, end=end))
    return result


def quarter_of(day: dt.date, *, today: dt.date | None = None) -> str | None:
    """Ключ четверти, в которую попадает день. None — вне учебного года."""
    for quarter in quarters(today or day):
        if quarter.covers(day):
            return quarter.key
    return None


def current_quarter(today: dt.date) -> str:
    """Текущая четверть. На каникулах — ближайшая прошедшая.

    Возвращает всегда что-то: экран калькулятора должен открываться и
    летом, просто с последней четвертью.
    """
    found = quarter_of(today)
    if found:
        return found
    return QUARTER_KEYS[0]
