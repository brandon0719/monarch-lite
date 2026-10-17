"""Net worth over time (M4 spec). Pure functions, integer cents."""
import datetime as dt
from bisect import bisect_right
from dataclasses import dataclass, field

LIABILITY_TYPES = ("credit", "loan")
REBUILD_TYPES = ("checking", "savings", "credit")
RANGE_DAYS = {"1M": 30, "3M": 91, "1Y": 365}


@dataclass
class AccountHistory:
    type: str
    is_manual: bool
    closed_at: dt.date | None
    snapshots: list[tuple[dt.date, int]]  # sorted by date
    txns: list[tuple[dt.date, int]] = field(default_factory=list)  # (posted date, cents); only used to rebuild

    def rebuilds(self) -> bool:
        return self.type in REBUILD_TYPES and not self.is_manual


def balance_on(acct: AccountHistory, day: dt.date) -> tuple[int, bool] | None:
    """(balance at end of `day`, estimated); None when the account doesn't count that day."""
    if not acct.snapshots or (acct.closed_at is not None and day > acct.closed_at):
        return None
    i = bisect_right(acct.snapshots, (day, float("inf")))
    if i:
        return acct.snapshots[i - 1][1], False
    first_day, first_balance = acct.snapshots[0]
    if acct.rebuilds():
        return first_balance - sum(c for posted, c in acct.txns if day < posted <= first_day), True
    return first_balance, True


def series(accounts: list[AccountHistory], start: dt.date, end: dt.date) -> list[dict]:
    points, day = [], start
    while day <= end:
        assets = liabilities = 0
        estimated = False
        for acct in accounts:
            # An account counts through its closed_at day, but never on the last day: the Overview's balances()
            # drops every account with closed_at set, and the last point must equal it.
            got = None if day == end and acct.closed_at is not None else balance_on(acct, day)
            if got is None:
                continue
            cents, est = got
            estimated |= est
            if acct.type in LIABILITY_TYPES:
                liabilities -= cents
            else:
                assets += cents
        points.append({"date": day, "assets_cents": assets, "liabilities_cents": liabilities,
                       "net_cents": assets - liabilities, "estimated": estimated})
        day += dt.timedelta(days=1)
    return points


def earliest(accounts: list[AccountHistory]) -> dt.date | None:
    days = []
    for acct in accounts:
        if not acct.snapshots:
            continue
        if acct.rebuilds() and acct.txns:
            days.append(min(posted for posted, _ in acct.txns))
        days.append(acct.snapshots[0][0])
    return min(days) if days else None


def range_start(range_: str, today: dt.date, first: dt.date) -> dt.date:
    if range_ == "ALL":
        return first
    start = dt.date(today.year, 1, 1) if range_ == "YTD" else today - dt.timedelta(days=RANGE_DAYS[range_])
    return max(start, first)
