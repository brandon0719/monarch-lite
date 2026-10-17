import datetime as dt

from app.models import Holding
from tests.conftest import make_account

TODAY = dt.date.today()


def add(db, account, symbol, shares, value, basis, description="Fund"):
    db.add(Holding(account_id=account.id, symbol=symbol, description=description, shares=shares,
                   market_value_cents=value, cost_basis_cents=basis, as_of=TODAY))
    db.commit()


def test_holdings_price_gain_class_and_order(client, db):
    b = make_account(db, name="B Brokerage", type="investment")
    a = make_account(db, name="A Brokerage", type="investment")
    hidden = make_account(db, name="Hidden", type="investment", is_hidden=True)
    closed = make_account(db, name="Closed", type="investment", closed_at=TODAY)
    add(db, b, "VTI", "4", 100000, 80000)
    add(db, a, "BND", "10", 50000, None, "Bond ETF")
    add(db, a, "QSWEEP", "250.00", 25000, None, "Chase Deposit Sweep Account")
    add(db, a, "ZERO", "0", 0, None)
    add(db, hidden, "HID", "1", 100, 100)
    add(db, closed, "OLD", "1", 100, 100)
    rows = client.get("/api/holdings").json()
    assert [(r["account_name"], r["symbol"]) for r in rows] == [
        ("A Brokerage", "BND"), ("A Brokerage", "QSWEEP"), ("A Brokerage", "ZERO"), ("B Brokerage", "VTI"),
    ]
    vti = rows[3]
    assert (vti["price_cents"], vti["gain_cents"], vti["gain_pct"], vti["asset_class"]) == (25000, 20000, 0.25, "stocks")
    assert (rows[0]["gain_cents"], rows[0]["gain_pct"], rows[0]["asset_class"]) == (None, None, "stocks")
    assert rows[1]["asset_class"] == "cash" and rows[2]["price_cents"] is None


def test_unparseable_shares_give_null_price_not_a_500(client, db):
    acct = make_account(db, name="Brokerage", type="investment")
    add(db, acct, "NANV", "NaN", 100, None)
    add(db, acct, "INFV", "Infinity", 100, None)
    add(db, acct, "TXTV", "abc", 100, None)
    r = client.get("/api/holdings")
    assert r.status_code == 200
    assert [row["price_cents"] for row in r.json()] == [None, None, None]


def test_price_rounds_half_up(client, db):
    add(db, make_account(db, name="Brokerage", type="investment"), "VTI", "2", 5, None)  # 2.5 -> 3, not banker's 2
    assert client.get("/api/holdings").json()[0]["price_cents"] == 3


def test_hidden_account_holdings_are_excluded(client, db):
    add(db, make_account(db, name="Hidden", type="investment", is_hidden=True), "HID", "1", 100, 100)
    assert client.get("/api/holdings").json() == []
