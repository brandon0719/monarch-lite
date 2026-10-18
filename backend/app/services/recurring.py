"""Recurring items: schedule math and detection (M3 round 1 spec). Pure functions, no DB. Integer cents only."""
import calendar
import datetime as dt
from statistics import median_low

CADENCES = ("weekly", "monthly", "yearly")
PAID_WINDOW_DAYS = 5
MIN_OCCURRENCES = 3
GAPS = {"weekly": (6, 8), "monthly": (27, 33), "yearly": (358, 372)}


def step(anchor: dt.date, cadence: str, k: int) -> dt.date:
    """The k-th date of the series; monthly/yearly keep the anchor's day, clamped to the month's end."""
    if cadence == "weekly":
        return anchor + dt.timedelta(days=7 * k)
    if cadence == "monthly":
        months = anchor.month - 1 + k
        year, month = anchor.year + months // 12, months % 12 + 1
    else:
        year, month = anchor.year + k, anchor.month
    return dt.date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def amount_matches(expected: int, amount: int) -> bool:
    """Same sign and within 10% of the expected amount."""
    return (amount > 0) == (expected > 0) and abs(amount - expected) * 10 <= abs(expected)


def next_due(anchor: dt.date, cadence: str, paid: list[dt.date]) -> dt.date:
    """The series date after the last paid one (or the anchor when none is paid).

    A payment pays series date s_k when it posted in [s_k - 5 days, s_(k+1) - 5 days), so a late posting anywhere in
    its cycle still counts. Payments before s_0 - 5 days are ignored; extras in one window pay that one date.
    """
    grace = dt.timedelta(days=PAID_WINDOW_DAYS)
    last = -1
    for p in sorted(paid):
        if p < step(anchor, cadence, 0) - grace:
            continue
        k = max(last, 0)
        while step(anchor, cadence, k + 1) - grace <= p:
            k += 1
        last = k
    return step(anchor, cadence, last + 1)


def is_late(due: dt.date, today: dt.date) -> bool:
    """Late only once the paid window around the due date has closed."""
    return today > due + dt.timedelta(days=PAID_WINDOW_DAYS)


def upcoming_dates(anchor: dt.date, cadence: str, due: dt.date, today: dt.date, horizon: dt.date) -> list[dt.date]:
    """`due` (even if past or late) plus later series dates from today through horizon."""
    out = [due] if due <= horizon else []
    k = 0
    while (day := step(anchor, cadence, k)) <= horizon:
        if day > due and day >= today:
            out.append(day)
        k += 1
    return out


def detect(txns: list[tuple[str, dt.date, int]]) -> list[dict]:
    """Suggest (merchant, sign) groups with >= 3 similar amounts on one regular cadence."""
    groups: dict[tuple[str, bool], list[tuple[dt.date, int]]] = {}
    for merchant, day, cents in txns:
        groups.setdefault((merchant, cents > 0), []).append((day, cents))
    out = []
    for (merchant, _), rows in groups.items():
        if len(rows) < MIN_OCCURRENCES:
            continue
        rows.sort()
        middle = median_low([cents for _, cents in rows])
        if not all(amount_matches(middle, cents) for _, cents in rows):
            continue
        gaps = [(b[0] - a[0]).days for a, b in zip(rows, rows[1:])]
        cadence = next((c for c, (lo, hi) in GAPS.items() if all(lo <= g <= hi for g in gaps)), None)
        if cadence is None:
            continue
        last_day, last_cents = rows[-1]
        out.append({"merchant": merchant, "cadence": cadence, "amount_cents": last_cents, "count": len(rows),
                    "last_date": last_day, "next_date": step(last_day, cadence, 1)})
    return sorted(out, key=lambda s: (s["last_date"], s["merchant"]), reverse=True)
