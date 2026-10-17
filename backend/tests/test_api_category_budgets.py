import datetime as dt

from sqlalchemy import func, select

from app.models import CategoryBudget
from tests.conftest import category, make_account, make_txn

AUG = dt.date(2026, 8, 10)


def put(client, cid, month, cents):
    return client.put(f"/api/category-budgets/{cid}", json={"month": month, "amount_cents": cents})


def rows(client, month):
    return client.get("/api/category-budgets", params={"month": month}).json()["rows"]


def test_budget_applies_from_start_month_onward(client, db):
    groceries = category(db, "Groceries").id
    assert put(client, groceries, "2026-08", 40000).json() == {"category_id": groceries, "month": "2026-08", "amount_cents": 40000}
    assert rows(client, "2026-07") == []
    assert [r["budget_cents"] for r in rows(client, "2026-08")] == [40000]
    assert [r["budget_cents"] for r in rows(client, "2026-10")] == [40000]


def test_setting_a_past_month_replaces_later_changes(client, db):
    groceries = category(db, "Groceries").id
    put(client, groceries, "2026-08", 40000)
    put(client, groceries, "2026-10", 50000)
    put(client, groceries, "2026-09", 45000)
    assert rows(client, "2026-08")[0]["budget_cents"] == 40000
    assert rows(client, "2026-10")[0]["budget_cents"] == 45000


def test_null_removes_budget_from_that_month(client, db):
    groceries = category(db, "Groceries").id
    put(client, groceries, "2026-08", 40000)
    put(client, groceries, "2026-09", None)
    assert len(rows(client, "2026-08")) == 1
    assert rows(client, "2026-09") == [] and rows(client, "2026-11") == []


def test_spent_remaining_and_pct_net_refunds_and_skip_hidden(client, db):
    acct, hidden = make_account(db), make_account(db, name="Hidden", is_hidden=True)
    groceries = category(db, "Groceries").id
    make_txn(db, acct, -30000, AUG, category_id=groceries)
    make_txn(db, acct, 5000, AUG, category_id=groceries)
    make_txn(db, hidden, -99999, AUG, category_id=groceries)
    put(client, groceries, "2026-08", 40000)
    (row,) = rows(client, "2026-08")
    assert row == {"category_id": groceries, "name": "Groceries", "bucket": "needs", "budget_cents": 40000,
                   "spent_cents": 25000, "remaining_cents": 15000, "pct_used": 0.625}


def test_refund_only_month_and_zero_budget(client, db):
    acct = make_account(db)
    shopping, travel = category(db, "Shopping").id, category(db, "Travel").id
    make_txn(db, acct, 2000, AUG, category_id=shopping)
    put(client, shopping, "2026-08", 10000)
    put(client, travel, "2026-08", 0)
    by_name = {r["name"]: r for r in rows(client, "2026-08")}
    assert (by_name["Shopping"]["spent_cents"], by_name["Shopping"]["remaining_cents"]) == (-2000, 12000)
    assert by_name["Travel"]["pct_used"] is None


def test_rows_sorted_by_pct_used_desc(client, db):
    acct = make_account(db)
    groceries, shopping = category(db, "Groceries").id, category(db, "Shopping").id
    make_txn(db, acct, -1000, AUG, category_id=groceries)
    make_txn(db, acct, -9000, AUG, category_id=shopping)
    put(client, groceries, "2026-08", 10000)
    put(client, shopping, "2026-08", 10000)
    assert [r["name"] for r in rows(client, "2026-08")] == ["Shopping", "Groceries"]


def test_unbudgeted_sums_positive_spend_in_budgetable_categories(client, db):
    acct = make_account(db)
    make_txn(db, acct, -7000, AUG, category_id=category(db, "Shopping").id)
    make_txn(db, acct, -3000, AUG, category_id=category(db, "Dining").id)
    make_txn(db, acct, 500, AUG, category_id=category(db, "Travel").id)          # net refund: not counted
    make_txn(db, acct, -100000, AUG, category_id=category(db, "Transfer").id)    # excluded bucket: not budgetable
    make_txn(db, acct, -1000, AUG, category_id=category(db, "Groceries").id)
    put(client, category(db, "Groceries").id, "2026-08", 40000)
    body = client.get("/api/category-budgets", params={"month": "2026-08"}).json()
    assert body["unbudgeted"] == {"spent_cents": 10000, "categories": 2}


def test_month_defaults_to_current(client):
    assert client.get("/api/category-budgets").json()["month"] == dt.date.today().strftime("%Y-%m")


def test_validation(client, db):
    groceries = category(db, "Groceries").id
    assert put(client, groceries, "2026-08", -1).status_code == 422
    assert put(client, groceries, "2026-13", 100).status_code == 422
    assert put(client, category(db, "Paycheck").id, "2026-08", 100).status_code == 422
    assert put(client, category(db, "Transfer").id, "2026-08", 100).status_code == 422
    assert put(client, 99999, "2026-08", 100).status_code == 404
    assert client.get("/api/category-budgets", params={"month": "2026-1"}).status_code == 422


def test_deleting_a_category_removes_its_budgets(client, db):
    created = client.post("/api/categories", json={"name": "Hobbies", "group_name": "Lifestyle", "bucket": "wants"}).json()
    put(client, created["id"], "2026-08", 5000)
    shopping = category(db, "Shopping").id
    assert client.delete(f"/api/categories/{created['id']}", params={"replacement_id": shopping}).status_code in (200, 204)
    db.expire_all()
    assert db.scalar(select(func.count(CategoryBudget.id))) == 0


def test_amount_is_capped_at_100_million_dollars(client, db):
    groceries = category(db, "Groceries").id
    assert put(client, groceries, "2026-08", 100_000_000_00).status_code == 200
    assert put(client, groceries, "2026-08", 100_000_000_00 + 1).status_code == 422


def test_rebucketed_category_drops_out_of_rows_and_unbudgeted(client, db):
    groceries = category(db, "Groceries").id
    make_txn(db, make_account(db), -5000, dt.date(2026, 8, 3), category_id=groceries)
    put(client, groceries, "2026-08", 40000)
    assert [r["category_id"] for r in rows(client, "2026-08")] == [groceries]
    assert client.patch(f"/api/categories/{groceries}", json={"bucket": "income"}).status_code == 200
    body = client.get("/api/category-budgets", params={"month": "2026-08"}).json()
    assert body["rows"] == []
    assert body["unbudgeted"] == {"spent_cents": 0, "categories": 0}
