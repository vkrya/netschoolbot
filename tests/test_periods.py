"""Тесты разбивки на четверти.

Границы приблизительные — школа своих не отдаёт, — но раскладка должна
быть непрерывной и не терять ни одного учебного дня.
"""

import datetime as dt

import pytest

from app.domain.periods import (
    QUARTER_KEYS,
    academic_year_start,
    current_quarter,
    quarter_of,
    quarters,
)


class TestAcademicYear:
    @pytest.mark.parametrize(
        "day,expected",
        [
            (dt.date(2026, 9, 1), 2026),
            (dt.date(2026, 12, 31), 2026),
            (dt.date(2027, 1, 1), 2026),
            (dt.date(2027, 5, 30), 2026),
            (dt.date(2027, 8, 31), 2026),
            (dt.date(2027, 9, 1), 2027),
        ],
    )
    def test_year_boundary_is_september(self, day, expected):
        assert academic_year_start(day) == expected


class TestQuarters:
    def test_four_quarters(self):
        assert [q.key for q in quarters(dt.date(2026, 10, 1))] == list(QUARTER_KEYS)

    def test_ranges_are_continuous(self):
        items = quarters(dt.date(2026, 10, 1))
        for earlier, later in zip(items, items[1:]):
            # Между четвертями не должно быть дыр: иначе оценка,
            # выставленная в этот день, потерялась бы в калькуляторе.
            assert earlier.end + dt.timedelta(days=1) == later.start

    def test_third_quarter_is_in_next_calendar_year(self):
        third = next(q for q in quarters(dt.date(2026, 10, 1)) if q.key == "q3")
        assert third.start == dt.date(2027, 1, 9)


class TestQuarterOf:
    @pytest.mark.parametrize(
        "day,expected",
        [
            (dt.date(2026, 9, 15), "q1"),
            (dt.date(2026, 10, 31), "q1"),
            (dt.date(2026, 11, 1), "q2"),
            (dt.date(2026, 12, 20), "q2"),
            (dt.date(2027, 1, 9), "q3"),
            (dt.date(2027, 3, 20), "q3"),
            (dt.date(2027, 4, 1), "q4"),
            (dt.date(2027, 5, 25), "q4"),
        ],
    )
    def test_mapping(self, day, expected):
        assert quarter_of(day) == expected

    def test_winter_holidays_belong_to_second_quarter(self):
        # 1 января — ещё вторая четверть: третья начинается 9-го.
        assert quarter_of(dt.date(2027, 1, 3)) == "q2"


class TestCurrentQuarter:
    def test_returns_something_even_in_summer(self):
        # Экран калькулятора должен открываться и на каникулах.
        assert current_quarter(dt.date(2027, 7, 15)) in QUARTER_KEYS

    def test_normal_day(self):
        assert current_quarter(dt.date(2026, 11, 20)) == "q2"
