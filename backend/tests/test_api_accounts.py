import datetime as dt

from app.models import BalanceSnapshot
from app.services import simplefin, sync
from tests.conftest import make_account


def test_lists_accounts_with_latest_balance(client, db):
    account = make_account(db, name="Everyday")
    db.add_all([
        BalanceSnapshot(account=account, date=dt.date(2026, 10, 1), balance_cents=100),
        BalanceSnapshot(account=account, date=dt.date(2026, 10, 2), balance_cents=250),
    ])
    db.commit()
    [body] = client.get("/api/accounts").json()
    assert (body["name"], body["balance_cents"], body["balance_date"]) == ("Everyday", 250, "2026-10-02")


def test_account_without_snapshot_has_null_balance(client, db):
    make_account(db)
    assert client.get("/api/accounts").json()[0]["balance_cents"] is None


def test_patch_account(client, db):
    account = make_account(db)
    body = client.patch(f"/api/accounts/{account.id}", json={"name": "Bills", "is_hidden": True, "closed_at": "2026-10-01"}).json()
    assert (body["name"], body["is_hidden"], body["closed_at"]) == ("Bills", True, "2026-10-01")
    assert client.patch(f"/api/accounts/{account.id}", json={"closed_at": None}).json()["closed_at"] is None


def test_patch_rejects_bad_type_null_name_and_unknown_id(client, db):
    account = make_account(db)
    assert client.patch(f"/api/accounts/{account.id}", json={"type": "boat"}).status_code == 422
    assert client.patch(f"/api/accounts/{account.id}", json={"name": None}).status_code == 422
    assert client.patch("/api/accounts/999", json={"name": "x"}).status_code == 404


def test_sync_endpoint_runs_and_lists(client, monkeypatch):
    monkeypatch.setattr(simplefin, "fetch_accounts", lambda start, end: {"errors": [], "accounts": []})
    run = client.post("/api/sync").json()
    assert run["status"] == "success"
    assert client.get("/api/sync/runs").json()[0]["id"] == run["id"]


def test_sync_conflict_returns_409(client):
    sync._lock.acquire()
    try:
        assert client.post("/api/sync").status_code == 409
    finally:
        sync._lock.release()


def test_rejected_patch_changes_nothing(client, db):
    account = make_account(db, name="Original")
    assert client.patch(f"/api/accounts/{account.id}", json={"name": "New", "type": None}).status_code == 422
    assert client.get("/api/accounts").json()[0]["name"] == "Original"
