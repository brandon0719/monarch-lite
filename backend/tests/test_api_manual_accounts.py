import datetime as dt

from sqlalchemy import func, select

from app.models import BalanceSnapshot, Goal
from tests.conftest import make_account

TODAY = dt.date.today()


def create(client, **kw):
    body = {"name": "Online Savings", "type": "savings", "balance_cents": 500000} | kw
    return client.post("/api/accounts", json=body)


def test_create_manual_account_with_balance(client, db):
    res = create(client)
    assert res.status_code == 201
    acct = res.json()
    assert (acct["name"], acct["institution"], acct["type"], acct["is_manual"]) == ("Online Savings", "Manual", "savings", True)
    assert (acct["balance_cents"], acct["balance_date"]) == (500000, str(TODAY))
    assert acct["last_synced_at"] is None and acct["last_error"] is None
    listed = {a["id"]: a for a in client.get("/api/accounts").json()}
    assert listed[acct["id"]]["is_manual"] is True


def test_update_balance_upserts_by_date(client, db):
    acct = create(client, as_of=str(TODAY - dt.timedelta(days=10))).json()
    res = client.post(f"/api/accounts/{acct['id']}/balance", json={"balance_cents": 520000})
    assert res.status_code == 200 and res.json()["balance_cents"] == 520000
    client.post(f"/api/accounts/{acct['id']}/balance", json={"balance_cents": 530000})  # same day: replaced
    count = db.scalar(select(func.count(BalanceSnapshot.id)).where(BalanceSnapshot.account_id == acct["id"]))
    assert count == 2
    assert client.get("/api/accounts").json()[0]["balance_cents"] == 530000


def test_manual_balance_counts_in_net_worth(client, db):
    before = client.get("/api/overview").json()["net_worth_cents"]
    create(client, balance_cents=250000)
    create(client, name="Car Loan", type="loan", balance_cents=-100000)
    assert client.get("/api/overview").json()["net_worth_cents"] == before + 150000


def test_validation_and_synced_accounts_are_protected(client, db):
    synced = make_account(db, name="Checking", type="checking")
    for bad in ({"name": " "}, {"type": "boat"}, {"balance_cents": 10**20}, {"as_of": str(TODAY + dt.timedelta(days=1))},
                {"name": "x" * 101}, {"institution": "x" * 101}):
        assert create(client, **bad).status_code == 422, bad
    assert create(client, name="x" * 100, institution="y" * 100).status_code == 201
    assert client.post(f"/api/accounts/{synced.id}/balance", json={"balance_cents": 1}).status_code == 422
    manual = create(client).json()
    future = str(TODAY + dt.timedelta(days=1))
    assert client.post(f"/api/accounts/{manual['id']}/balance", json={"balance_cents": 1, "as_of": future}).status_code == 422
    assert client.post("/api/accounts/99999/balance", json={"balance_cents": 1}).status_code == 404
    assert client.delete(f"/api/accounts/{synced.id}").status_code == 409
    assert client.delete("/api/accounts/99999").status_code == 404
    assert client.patch(f"/api/accounts/{manual['id']}", json={"name": "x" * 101}).status_code == 422


def test_delete_manual_account_cascades_snapshots_and_goal_link(client, db):
    manual = create(client).json()
    goal = client.post("/api/goals", json={"name": "Rainy day", "target_cents": 1000000, "kind": "linked", "account_ids": [manual["id"]]}).json()
    assert goal["current_cents"] == 500000
    assert client.delete(f"/api/accounts/{manual['id']}").status_code == 204
    db.expire_all()
    assert db.scalar(select(func.count(BalanceSnapshot.id))) == 0
    assert client.get("/api/goals").json()[0]["accounts"] == []
    assert db.get(Goal, goal["id"]) is not None
