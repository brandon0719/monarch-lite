import datetime as dt

from app.services import networth as nw

D = dt.date


def test_balance_on_real_rebuilt_flat_and_closed():
    chk = nw.AccountHistory(type="checking", is_manual=False, closed_at=None,
                            snapshots=[(D(2026, 10, 16), 100000), (D(2026, 10, 18), 90000)],
                            txns=[(D(2026, 10, 10), -5000), (D(2026, 10, 16), 2000), (D(2026, 10, 1), 30000)])
    assert nw.balance_on(chk, D(2026, 10, 17)) == (100000, False)
    assert nw.balance_on(chk, D(2026, 10, 18)) == (90000, False)
    assert nw.balance_on(chk, D(2026, 10, 15)) == (98000, True)    # undo the 10/16 +20.00
    assert nw.balance_on(chk, D(2026, 10, 9)) == (103000, True)    # also undo the 10/10 -50.00
    inv = nw.AccountHistory(type="investment", is_manual=False, closed_at=None, snapshots=[(D(2026, 10, 16), 500000)])
    assert nw.balance_on(inv, D(2026, 9, 1)) == (500000, True)
    manual = nw.AccountHistory(type="savings", is_manual=True, closed_at=None, snapshots=[(D(2026, 10, 16), 7000)],
                               txns=[(D(2026, 10, 10), 999)])
    assert nw.balance_on(manual, D(2026, 10, 1)) == (7000, True)
    closed = nw.AccountHistory(type="checking", is_manual=False, closed_at=D(2026, 10, 17), snapshots=[(D(2026, 10, 16), 1)])
    assert nw.balance_on(closed, D(2026, 10, 18)) is None
    assert nw.balance_on(nw.AccountHistory(type="checking", is_manual=False, closed_at=None, snapshots=[]), D(2026, 10, 1)) is None


def test_series_splits_assets_and_liabilities():
    chk = nw.AccountHistory(type="checking", is_manual=False, closed_at=None, snapshots=[(D(2026, 10, 2), 100000)],
                            txns=[(D(2026, 10, 2), 10000)])
    card = nw.AccountHistory(type="credit", is_manual=False, closed_at=None, snapshots=[(D(2026, 10, 1), -30000)])
    pts = nw.series([chk, card], D(2026, 10, 1), D(2026, 10, 2))
    assert pts == [
        {"date": D(2026, 10, 1), "assets_cents": 90000, "liabilities_cents": 30000, "net_cents": 60000, "estimated": True},
        {"date": D(2026, 10, 2), "assets_cents": 100000, "liabilities_cents": 30000, "net_cents": 70000, "estimated": False},
    ]


def test_range_start_and_earliest():
    today = D(2026, 10, 17)
    assert nw.range_start("1M", today, D(2020, 1, 1)) == D(2026, 9, 17)
    assert nw.range_start("3M", today, D(2020, 1, 1)) == D(2026, 7, 18)
    assert nw.range_start("YTD", today, D(2020, 1, 1)) == D(2026, 1, 1)
    assert nw.range_start("1Y", today, D(2020, 1, 1)) == D(2025, 10, 17)
    assert nw.range_start("ALL", today, D(2026, 5, 8)) == D(2026, 5, 8)
    assert nw.range_start("1Y", today, D(2026, 5, 8)) == D(2026, 5, 8)   # clamped
    chk = nw.AccountHistory(type="checking", is_manual=False, closed_at=None, snapshots=[(D(2026, 10, 16), 1)], txns=[(D(2026, 5, 8), 1)])
    inv = nw.AccountHistory(type="investment", is_manual=False, closed_at=None, snapshots=[(D(2026, 10, 16), 1)])
    assert nw.earliest([chk, inv]) == D(2026, 5, 8) and nw.earliest([inv]) == D(2026, 10, 16) and nw.earliest([]) is None


def test_series_excludes_a_closed_account_from_the_last_day_only():
    acct = nw.AccountHistory(type="checking", is_manual=False, closed_at=D(2026, 10, 2), snapshots=[(D(2026, 10, 1), 500)])
    other = nw.AccountHistory(type="savings", is_manual=True, closed_at=None, snapshots=[(D(2026, 10, 1), 100)])
    nets = [p["net_cents"] for p in nw.series([acct, other], D(2026, 10, 1), D(2026, 10, 4))]
    assert nets == [600, 600, 100, 100]    # counted through day == closed_at, then gone
    assert [p["net_cents"] for p in nw.series([acct, other], D(2026, 10, 1), D(2026, 10, 2))] == [600, 100]  # last day excluded


def test_rebuild_account_without_transactions_is_held_flat():
    chk = nw.AccountHistory(type="checking", is_manual=False, closed_at=None, snapshots=[(D(2026, 10, 3), 4200)])
    assert nw.balance_on(chk, D(2026, 10, 1)) == (4200, True)
    assert nw.earliest([chk]) == D(2026, 10, 3)


def test_future_only_snapshots():
    inv = nw.AccountHistory(type="investment", is_manual=False, closed_at=None, snapshots=[(D(2026, 10, 20), 900)])
    assert nw.balance_on(inv, D(2026, 10, 17)) == (900, True)
    assert nw.series([inv], D(2026, 10, 20), D(2026, 10, 20))[0]["estimated"] is False
