import datetime as dt

from app.models import BalanceSnapshot, SyncRun
from tests.conftest import category, make_account, make_txn


def snap(db, account, cents, day=dt.date(2026, 10, 1)):
    db.add(BalanceSnapshot(account=account, date=day, balance_cents=cents))
    db.commit()


def test_balances_group_latest_snapshot_and_skip_closed_or_hidden(client, db):
    chk = make_account(db, type="checking")
    sav = make_account(db, name="Savings", type="savings")
    card = make_account(db, name="Card", type="credit")
    inv = make_account(db, name="Brokerage", type="investment")
    hidden = make_account(db, name="Old", type="checking", is_hidden=True)
    closed = make_account(db, name="Closed", type="savings", closed_at=dt.date(2026, 1, 1))
    snap(db, chk, 10000, dt.date(2026, 10, 1))
    snap(db, chk, 15000, dt.date(2026, 10, 2))  # latest wins
    snap(db, sav, 100000)
    snap(db, card, -5000)
    snap(db, inv, 50000)
    snap(db, hidden, 999999)
    snap(db, closed, 888888)
    body = client.get("/api/overview").json()
    assert body["balances"] == {"cash": 115000, "investments": 50000, "credit": -5000, "loans": 0, "other": 0}
    assert body["net_worth_cents"] == 160000


def test_spending_buckets_refunds_uncategorized_and_month_boundary(client, db):
    acct = make_account(db)
    hidden = make_account(db, name="Hidden", is_hidden=True)
    oct_ = lambda d: dt.date(2026, 10, d)
    dining, rent = category(db, "Dining"), category(db, "Rent")
    make_txn(db, acct, -5000, oct_(3), category_id=dining.id)
    make_txn(db, acct, 1000, oct_(4), category_id=dining.id)  # refund nets out
    make_txn(db, acct, -120000, oct_(1), category_id=rent.id)
    make_txn(db, acct, -2000, oct_(5))  # uncategorized outflow counts
    make_txn(db, acct, 300000, oct_(5))  # uncategorized inflow ignored
    make_txn(db, acct, -50000, oct_(6), category_id=category(db, "Savings Transfer").id)
    make_txn(db, acct, -9999, oct_(7), category_id=category(db, "Transfer").id)
    make_txn(db, acct, 400000, oct_(8), category_id=category(db, "Paycheck").id)
    make_txn(db, acct, -7000, dt.date(2026, 9, 30), category_id=dining.id)  # previous month
    make_txn(db, acct, -100, dt.date(2026, 11, 1), category_id=dining.id)  # next month
    make_txn(db, hidden, -4242, oct_(9), category_id=dining.id)  # hidden account
    body = client.get("/api/overview", params={"month": "2026-10"}).json()
    assert body["month"] == "2026-10"
    assert body["spending_by_category"] == [
        {"category_id": rent.id, "name": "Rent", "cents": 120000},
        {"category_id": dining.id, "name": "Dining", "cents": 4000},
        {"category_id": None, "name": "Uncategorized", "cents": 2000},
    ]
    assert body["spent_cents"] == 126000


def test_review_counts_use_last_90_days(client, db):
    acct = make_account(db)
    today = dt.date.today()
    make_txn(db, acct, -100, today - dt.timedelta(days=10))  # unreviewed + uncategorized
    make_txn(db, acct, -100, today - dt.timedelta(days=100))  # outside window
    make_txn(db, acct, -100, today - dt.timedelta(days=5), reviewed_at=dt.datetime(2026, 1, 1),
             category_id=category(db, "Dining").id)
    body = client.get("/api/overview").json()
    assert (body["to_review"], body["uncategorized"]) == (1, 1)


def test_recent_is_newest_eight(client, db):
    acct = make_account(db)
    for i in range(10):
        make_txn(db, acct, -100 - i, dt.date(2026, 10, 1) + dt.timedelta(days=i))
    recent = client.get("/api/overview").json()["recent"]
    assert len(recent) == 8 and recent[0]["posted_date"] == "2026-10-10"


def test_last_synced_ignores_failed_runs(client, db):
    db.add_all([
        SyncRun(started_at=dt.datetime(2026, 10, 1, 9), finished_at=dt.datetime(2026, 10, 1, 9, 1), status="success"),
        SyncRun(started_at=dt.datetime(2026, 10, 2, 9), finished_at=dt.datetime(2026, 10, 2, 9, 1), status="failed"),
    ])
    db.commit()
    assert client.get("/api/overview").json()["last_synced_at"] == "2026-10-01T09:01:00"


def test_bad_month_is_422(client):
    for bad in ("2026-13", "oct", "2026-1", "9999-12"):
        assert client.get("/api/overview", params={"month": bad}).status_code == 422


def test_spent_nets_refunds_at_bucket_level_and_matches_cashflow(client, db):
    # A category whose refunds exceed its spend must reduce `spent`, exactly as the meters do.
    acct = make_account(db)
    today = dt.date.today()
    month = today.strftime("%Y-%m")
    make_txn(db, acct, -10000, today.replace(day=1), category_id=category(db, "Groceries").id)
    make_txn(db, acct, 3000, today.replace(day=1), category_id=category(db, "Dining").id)  # net-negative category
    make_txn(db, acct, -2000, today.replace(day=1))  # uncategorized outflow
    body = client.get("/api/overview", params={"month": month}).json()
    assert body["spent_cents"] == 10000 - 3000 + 2000
    assert all(r["cents"] > 0 for r in body["spending_by_category"])  # chart rows stay clamped
    cash = client.get("/api/cashflow", params={"months": 1}).json()["months"][0]
    assert cash["month"] == month and cash["spent_cents"] == body["spent_cents"]
