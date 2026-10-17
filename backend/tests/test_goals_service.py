import datetime as dt
import math

from app.services import goals as g

D = dt.date
PER_MONTH = 365.25 / 12


def test_monthly_rate_needs_two_weeks_of_history():
    assert g.monthly_rate(10000, 13) is None
    assert g.monthly_rate(30000, 90) == round(30000 * PER_MONTH / 90)
    assert g.monthly_rate(-30000, 90) == round(-30000 * PER_MONTH / 90)


def test_needed_per_month():
    assert g.needed_per_month(0, D(2026, 1, 1), D(2026, 12, 1)) == 0
    assert g.needed_per_month(120000, D(2026, 1, 1), D(2026, 1, 20)) == 120000   # under a month left
    assert g.needed_per_month(120000, D(2026, 1, 1), D(2025, 12, 1)) == 120000   # date already passed
    assert g.needed_per_month(120000, D(2026, 1, 1), D(2027, 1, 1)) == math.ceil(120000 / (365 / PER_MONTH))


def test_status():
    assert g.status(100, 100, None, 0, True) == "done"
    assert g.status(50, 100, 5, 10, False) == "no_date"
    assert g.status(50, 100, None, 10, True) == "unknown"
    assert g.status(50, 100, 10, 10, True) == "on_track"
    assert g.status(50, 100, 9, 10, True) == "behind"


def test_reach_by():
    day = D(2026, 1, 1)
    assert g.reach_by(day, 0, 100) is None and g.reach_by(day, 100, 0) is None and g.reach_by(day, 100, None) is None
    assert g.reach_by(day, 300, 100) == day + dt.timedelta(days=math.ceil(3 * PER_MONTH))


def test_reach_by_past_year_9999_is_none():
    assert g.reach_by(D(2026, 1, 1), 100_000_000, 101) is None  # ~1e6 months away
    assert g.reach_by(D(2026, 1, 1), 100, 1) is not None  # ~8 years is fine
