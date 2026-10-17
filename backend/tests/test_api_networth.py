import datetime as dt

from app.models import BalanceSnapshot, Holding
from tests.conftest import make_account, make_txn

TODAY = dt.date.today()


def d(n):
    return TODAY + dt.timedelta(days=n)


def test_networth_series_rebuild_hidden_and_validation(client, db):
    chk = make_account(db, type="checking")
    inv = make_account(db, name="Brokerage", type="investment")
    hidden = make_account(db, name="Hidden", type="savings", is_hidden=True)
    db.add_all([BalanceSnapshot(account_id=chk.id, date=d(-1), balance_cents=100000),
                BalanceSnapshot(account_id=inv.id, date=d(-1), balance_cents=500000),
                BalanceSnapshot(account_id=hidden.id, date=d(-1), balance_cents=999999)])
    db.commit()
    make_txn(db, chk, -20000, d(-3))   # earliest rebuild data: the series starts here
    make_txn(db, chk, 5000, d(-2))
    body = client.get("/api/networth", params={"range": "ALL"}).json()
    by_day = {p["date"]: p for p in body["points"]}
    assert body["points"][0]["date"] == str(d(-3)) and body["points"][-1]["date"] == str(TODAY)
    # End of d(-3): undo only the +50.00 posted on d(-2) -> 100000 - 5000 = 95000 checking
    assert by_day[str(d(-3))] == {"date": str(d(-3)), "assets_cents": 595000, "liabilities_cents": 0, "net_cents": 595000, "estimated": True}
    assert by_day[str(d(-2))]["net_cents"] == 600000 and by_day[str(d(-2))]["estimated"] is True
    assert by_day[str(d(-1))]["estimated"] is False and by_day[str(TODAY)]["net_cents"] == 600000
    assert body["change_cents"] == 5000 and body["first_actual_date"] == str(d(-1))
    assert client.get("/api/networth").status_code == 200
    assert client.get("/api/networth", params={"range": "5Y"}).status_code == 422


def test_networth_empty(client):
    assert client.get("/api/networth").json() == {"points": [], "change_cents": 0, "first_actual_date": None}


def snap(db, account, day, cents):
    db.add(BalanceSnapshot(account_id=account.id, date=day, balance_cents=cents))
    db.commit()


def test_last_point_equals_overview_net_worth(client, db):
    chk = make_account(db, name="Checking", type="checking")
    manual = make_account(db, name="Savings", type="savings", is_manual=True)
    card = make_account(db, name="Card", type="credit")
    inv = make_account(db, name="Brokerage", type="investment")
    closed_past = make_account(db, name="Old", type="checking", closed_at=d(-2))
    closed_today = make_account(db, name="Closing", type="savings", closed_at=TODAY)
    hidden = make_account(db, name="Hidden", type="savings", is_hidden=True)
    snap(db, chk, d(-2), 100000)
    snap(db, chk, d(1), 120000)           # an evening UTC sync dates the snapshot "tomorrow"
    snap(db, manual, d(-5), 7000)
    snap(db, card, d(-1), -30000)
    snap(db, inv, d(-1), 500000)
    db.add(Holding(account_id=inv.id, symbol="VTI", description="ETF", shares="4", market_value_cents=480000,
                   cost_basis_cents=None, as_of=TODAY))
    db.commit()
    snap(db, closed_past, d(-3), 9999)
    snap(db, closed_today, d(-1), 8888)
    snap(db, hidden, d(-1), 777777)
    expected = 120000 + 7000 - 30000 + 500000
    assert client.get("/api/overview").json()["net_worth_cents"] == expected
    for rng in ("1M", "3M", "YTD", "1Y", "ALL"):
        points = client.get("/api/networth", params={"range": rng}).json()["points"]
        assert points[-1]["date"] == str(d(1)) and points[-1]["net_cents"] == expected, rng
    # Past days still count a closed account up to and including its close date.
    by_day = {p["date"]: p for p in client.get("/api/networth", params={"range": "ALL"}).json()["points"]}
    assert by_day[str(d(-2))]["net_cents"] == 100000 + 7000 - 30000 + 500000 + 9999 + 8888  # card/investment held flat before their first snapshot
    assert by_day[str(d(-1))]["net_cents"] == 100000 + 7000 - 30000 + 500000 + 8888
    assert by_day[str(TODAY)]["net_cents"] == 100000 + 7000 - 30000 + 500000 + 8888


def test_only_future_dated_snapshots_still_chart(client, db):
    inv = make_account(db, name="Brokerage", type="investment")
    snap(db, inv, d(1), 500000)
    for rng in ("1M", "YTD", "1Y", "ALL"):
        points = client.get("/api/networth", params={"range": rng}).json()["points"]
        assert [(p["date"], p["net_cents"]) for p in points] == [(str(d(1)), 500000)], rng


def test_ranges_start_where_expected(client, db):
    chk = make_account(db, name="Checking", type="checking")
    snap(db, chk, d(-400), 100000)
    starts = {r: client.get("/api/networth", params={"range": r}).json()["points"][0]["date"] for r in ("1M", "YTD", "1Y", "ALL")}
    assert starts["1M"] == str(d(-30)) and starts["1Y"] == str(d(-365)) and starts["ALL"] == str(d(-400))
    assert starts["YTD"] == str(max(dt.date(TODAY.year, 1, 1), d(-400)))


def test_first_actual_date_is_the_latest_first_snapshot(client, db):
    chk = make_account(db, name="Checking", type="checking")
    k401 = make_account(db, name="401k", type="investment")
    snap(db, chk, d(-10), 100000)
    snap(db, k401, d(-2), 500000)
    snap(db, k401, d(-1), 510000)
    body = client.get("/api/networth", params={"range": "ALL"}).json()
    assert body["first_actual_date"] == str(d(-2))
    flags = {p["date"]: p["estimated"] for p in body["points"]}
    assert flags[str(d(-3))] is True and flags[str(d(-2))] is False
