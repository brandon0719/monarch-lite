"""RSU vest schedules (M5 round 1 spec). Pure functions; whole shares."""
import calendar
import datetime as dt

SCHEDULES = ("amazon_5_15_40_40", "semiannual", "custom")
AMAZON_PCTS = (5, 15, 20, 20, 20, 20)
MAX_SEMIANNUAL = 20


def add_months(day: dt.date, months: int, dom: int | None = None) -> dt.date:
    """`day` moved by `months`, on day-of-month `dom` (default: day.day), clamped to the month's end."""
    total = day.month - 1 + months
    year, month = day.year + total // 12, total % 12 + 1
    return dt.date(year, month, min(dom or day.day, calendar.monthrange(year, month)[1]))


def split(total: int, weights: tuple[int, ...] | list[int]) -> list[int]:
    """Floor each share of `total`; the remainder goes to the last so the parts sum exactly."""
    parts = [total * w // sum(weights) for w in weights]
    parts[-1] += total - sum(parts)
    return parts


def amazon_5_15_40_40(start: dt.date, total: int) -> list[tuple[dt.date, int]]:
    """5% / 15% on the 15th of the 1st / 2nd anniversary month, then 20% every 6 months."""
    second = dt.date(start.year + 2, start.month, 15)
    dates = [dt.date(start.year + 1, start.month, 15), second] + [add_months(second, 6 * k) for k in range(1, 5)]
    return [(d, s) for d, s in zip(dates, split(total, AMAZON_PCTS)) if s > 0]


def semiannual(first_vest: dt.date, total: int, count: int) -> list[tuple[dt.date, int]]:
    shares = split(total, [1] * count)
    return [(add_months(first_vest, 6 * k, first_vest.day), s) for k, s in enumerate(shares) if s > 0]


def check_custom(vests: list[tuple[dt.date, int]], total: int) -> list[tuple[dt.date, int]]:
    if not vests:
        raise ValueError("Add at least one vest")
    if len({d for d, _ in vests}) != len(vests):
        raise ValueError("Each vest date can appear only once")
    if any(s <= 0 for _, s in vests):
        raise ValueError("Each vest needs at least 1 share")
    if sum(s for _, s in vests) != total:
        raise ValueError(f"Vest shares must add up to the grant total ({total})")
    return sorted(vests)


def build_vests(schedule: str, start: dt.date, total: int, first_vest: dt.date | None = None,
                count: int | None = None, custom: list[tuple[dt.date, int]] | None = None) -> list[tuple[dt.date, int]]:
    if schedule == "amazon_5_15_40_40":
        return amazon_5_15_40_40(start, total)
    if schedule == "semiannual":
        if first_vest is None or count is None:
            raise ValueError("A semiannual schedule needs a first vest date and a number of vests")
        if not 1 <= count <= MAX_SEMIANNUAL:
            raise ValueError(f"Number of vests must be 1 to {MAX_SEMIANNUAL}")
        return semiannual(first_vest, total, count)
    if schedule == "custom":
        return check_custom(custom or [], total)
    raise ValueError(f"Unknown schedule: {schedule}")
