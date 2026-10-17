"""Savings goals: progress math (M3 round 2 spec). Pure functions, integer cents."""
import datetime as dt
import math

DAYS_PER_MONTH = 365.25 / 12
RATE_WINDOW_DAYS = 90
MIN_HISTORY_DAYS = 14
MAX_REACH_DAYS = 36525  # past ~100 years there is no useful date (and dates overflow at year 9999)


def monthly_rate(delta_cents: int, days: int) -> int | None:
    """Average change per month over `days`; None under two weeks of history."""
    if days < MIN_HISTORY_DAYS:
        return None
    return round(delta_cents * DAYS_PER_MONTH / days)


def needed_per_month(remaining: int, today: dt.date, target_date: dt.date) -> int:
    """Monthly amount needed to reach the target by its date; the whole remainder when under a month is left."""
    if remaining <= 0:
        return 0
    months = max((target_date - today).days, 0) / DAYS_PER_MONTH
    return remaining if months < 1 else math.ceil(remaining / months)


def status(current: int, target: int, rate: int | None, needed: int, has_date: bool) -> str:
    if current >= target:
        return "done"
    if not has_date:
        return "no_date"
    if rate is None:
        return "unknown"
    return "on_track" if rate >= needed else "behind"


def reach_by(today: dt.date, remaining: int, rate: int | None) -> dt.date | None:
    """When the goal is reached at the current monthly rate; None if done, not growing, or over a century away."""
    if remaining <= 0 or rate is None or rate <= 0:
        return None
    days = math.ceil(remaining / rate * DAYS_PER_MONTH)
    return None if days > MAX_REACH_DAYS else today + dt.timedelta(days=days)
