import datetime as dt
import time

from sqlalchemy import insert

from app.models import Transaction
from tests.conftest import category, make_account, make_txn


def setup(db):
    checking = make_account(db, name="Checking")
    a = make_txn(db, checking, -999, dt.date(2026, 10, 1), "NETFLIX.COM", merchant="Netflix")
    b = make_txn(db, checking, -4500, dt.date(2026, 10, 2), "TRADER JOES", merchant="Trader Joes")
    c = make_txn(db, checking, 250000, dt.date(2026, 10, 3), "PAYROLL", merchant="Payroll", reviewed_at=dt.datetime(2026, 10, 3))
    return checking, a, b, c


def ids(client, **params):
    return [t["id"] for t in client.get("/api/transactions", params=params).json()["items"]]


def test_newest_first_with_keyset_cursor(client, db):
    _, a, b, c = setup(db)
    page = client.get("/api/transactions", params={"limit": 2}).json()
    assert [t["id"] for t in page["items"]] == [c.id, b.id] and page["total"] == 3
    page2 = client.get("/api/transactions", params={"limit": 2, "cursor": page["next_cursor"]}).json()
    assert [t["id"] for t in page2["items"]] == [a.id] and page2["next_cursor"] is None


def test_filters(client, db):
    _, a, b, c = setup(db)
    assert ids(client, q="trader") == [b.id]
    assert ids(client, min_cents=-5000, max_cents=-1000) == [b.id]
    assert ids(client, needs_review=True) == [b.id, a.id]
    assert ids(client, uncategorized=True) == [c.id, b.id, a.id]
    assert ids(client, start="2026-10-02", end="2026-10-02") == [b.id]


def test_hidden_accounts_excluded_unless_selected(client, db):
    checking, *_ = setup(db)
    checking.is_hidden = True
    db.commit()
    assert client.get("/api/transactions").json()["total"] == 0
    assert client.get("/api/transactions", params={"account_id": checking.id}).json()["total"] == 3


def test_bad_cursor_is_422(client):
    assert client.get("/api/transactions", params={"cursor": "nope"}).status_code == 422


def test_patch_category_marks_user(client, db):
    _, a, *_ = setup(db)
    body = client.patch(f"/api/transactions/{a.id}", json={"category_id": category(db, "Dining").id}).json()
    assert (body["category_name"], body["category_source"]) == ("Dining", "user")
    assert client.patch(f"/api/transactions/{a.id}", json={"category_id": 9999}).status_code == 404
    assert client.patch("/api/transactions/9999", json={"notes": "x"}).status_code == 404


def test_patch_merchant_locks_and_tags_dedupe(client, db):
    _, a, *_ = setup(db)
    body = client.patch(f"/api/transactions/{a.id}", json={"merchant": " Netflix Inc ", "tag_names": ["tv", "tv", " shared ", ""]}).json()
    assert body["merchant"] == "Netflix Inc"
    assert sorted(t["name"] for t in body["tags"]) == ["shared", "tv"]
    db.refresh(a)
    assert a.merchant_locked


def test_patch_reviewed_and_notes(client, db):
    _, a, *_ = setup(db)
    body = client.patch(f"/api/transactions/{a.id}", json={"reviewed": True, "notes": "shared with roommate"}).json()
    assert body["reviewed_at"] is not None and body["notes"] == "shared with roommate"
    assert client.patch(f"/api/transactions/{a.id}", json={"reviewed": False}).json()["reviewed_at"] is None


def test_bulk_review(client, db):
    _, a, b, _ = setup(db)
    assert client.post("/api/transactions/review", json={"ids": [a.id, b.id]}).json() == {"updated": 2}
    assert ids(client, needs_review=True) == []


def test_unlink_endpoint(client, db):
    checking, a, *_ = setup(db)
    savings = make_account(db, name="Savings", type="savings")
    twin = make_txn(db, savings, 999, dt.date(2026, 10, 1))
    a.transfer_pair_id, twin.transfer_pair_id = twin.id, a.id
    db.commit()
    assert client.delete(f"/api/transactions/{a.id}/transfer").status_code == 204
    db.refresh(twin)
    assert twin.transfer_pair_id is None
    assert client.delete(f"/api/transactions/{a.id}/transfer").status_code == 409


def test_25k_rows_list_under_a_second(client, db):
    account = make_account(db)
    db.execute(insert(Transaction), [
        {
            "account_id": account.id, "external_id": f"p{i}",
            "posted_date": dt.date(2021, 1, 1) + dt.timedelta(days=i % 1800),
            "amount_cents": -(i % 9000), "raw_description": f"MERCHANT {i % 300}", "merchant": f"Merchant {i % 300}",
            "merchant_locked": False, "category_source": "none", "created_at": dt.datetime(2026, 1, 1),
        }
        for i in range(25_000)
    ])
    db.commit()
    start = time.perf_counter()
    first = client.get("/api/transactions").json()
    searched = client.get("/api/transactions", params={"q": "merchant 42"}).json()
    elapsed = time.perf_counter() - start
    assert first["total"] == 25_000 and searched["total"] > 0
    assert elapsed < 1.0, f"took {elapsed:.2f}s (NFR-PERF-01)"


def test_patch_rejects_blank_merchant(client, db):
    _, a, *_ = setup(db)
    assert client.patch(f"/api/transactions/{a.id}", json={"merchant": "   "}).status_code == 422
    db.refresh(a)
    assert (a.merchant, a.merchant_locked) == ("Netflix", False)


def test_pending_list_is_newest_first_and_hides_hidden_accounts(client, db):
    from app.models import PendingTransaction
    card = make_account(db, name="Card")
    hidden = make_account(db, name="Old", is_hidden=True)
    db.add_all([
        PendingTransaction(account=card, external_id="p1", posted_date=dt.date(2026, 10, 19), amount_cents=-645, raw_description="SQ *BLUE BOTTLE 0423"),
        PendingTransaction(account=card, external_id="p2", posted_date=dt.date(2026, 10, 20), amount_cents=-2410, raw_description="UBER *EATS", raw_payee="Uber Eats"),
        PendingTransaction(account=hidden, external_id="p3", posted_date=dt.date(2026, 10, 20), amount_cents=-100, raw_description="X"),
    ])
    db.commit()
    rows = client.get("/api/transactions/pending").json()
    assert [(r["merchant"], r["account_name"], r["posted_date"], r["amount_cents"]) for r in rows] == [
        ("Uber Eats", "Card", "2026-10-20", -2410), ("Blue Bottle", "Card", "2026-10-19", -645),
    ]
    assert [r["amount_cents"] for r in client.get("/api/transactions/pending", params={"account_id": hidden.id}).json()] == [-100]
    assert client.get("/api/transactions/pending", params={"account_id": 0}).status_code == 422
