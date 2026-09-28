"""Tests for configuration loading."""

from datetime import UTC, date, datetime

import pytest

from bess_markowitz.config import StudyPeriod, load_study_period


def test_study_period_file_is_first_half_of_2026():
    period = load_study_period()

    assert period.start_date == date(2026, 1, 1)
    assert period.end_date == date(2026, 6, 30)
    assert period.timezone == "Europe/Helsinki"


def test_study_period_bounds_are_helsinki_midnights_in_utc():
    period = StudyPeriod(date(2026, 1, 1), date(2026, 6, 30), "Europe/Helsinki")

    assert period.start.astimezone(UTC) == datetime(2025, 12, 31, 22, tzinfo=UTC)  # EET, +2
    assert period.end.astimezone(UTC) == datetime(2026, 6, 30, 21, tzinfo=UTC)  # EEST, +3


def test_study_period_hour_count_includes_dst_switch():
    period = StudyPeriod(date(2026, 1, 1), date(2026, 6, 30), "Europe/Helsinki")

    hours = (period.end.astimezone(UTC) - period.start.astimezone(UTC)).total_seconds() / 3600
    assert hours == 181 * 24 - 1  # spring-forward on 2026-03-29 loses one hour


def test_study_period_rejects_reversed_dates():
    with pytest.raises(ValueError, match="before it starts"):
        StudyPeriod(date(2026, 6, 30), date(2026, 1, 1), "Europe/Helsinki")
