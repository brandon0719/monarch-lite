import datetime as dt
import math

from app.models import BalanceSnapshot
from tests.conftest import make_account

TODAY = dt.date.today()
PER_MONTH = 365.25 / 12


def d(n):
    return TODAY + dt.timedelta(days=n)


def snap(db, account, day, cents):
    db.add(BalanceSnapshot(account_id=account.id, date=day, balance_cents=cents))
    db.commit()


def goals(client):
    return client.get("/api/goals").json()


def post(client, **kw):
    return client.post("/api/goals", json=kw)


def test_linked_goal_progress_rate_and_on_track(client, db):
    sav = make_account(db, name="Savings", type="savings")
    snap(db, sav, d(-120), 100000)
    snap(db, sav, d(-91), 200000)
    snap(db, sav, d(-1), 500000)
    res = post(client, name="Emergency", target_cents=1100000, target_date=str(d(365)), kind="linked", account_ids=[sav.id])
    assert res.status_code == 201
    goal = res.json()
    assert (goal["current_cents"], goal["pct"], goal["history_days"]) == (500000, round(500000 / 1100000, 4), 91)
    assert goal["rate_cents"] == round(300000 * PER_MONTH / 91)
    assert goal["needed_cents"] == math.ceil(600000 / (365 / PER_MONTH))
    assert goal["status"] == "on_track" and goal["reach_by"] is None
    assert goal["accounts"] == [{"id": sav.id, "name": "Savings"}] and goal["contributions"] == []


def test_short_history_is_unknown_and_slow_saving_is_behind(client, db):
    sav = make_account(db, name="Savings", type="savings")
    snap(db, sav, d(-5), 0)
    snap(db, sav, d(0), 100000)
    goal = post(client, name="Trip", target_cents=500000, target_date=str(d(60)), kind="linked", account_ids=[sav.id]).json()
    assert (goal["rate_cents"], goal["history_days"], goal["status"]) == (None, 5, "unknown")
    inv = make_account(db, name="Brokerage", type="investment")
    snap(db, inv, d(-100), 100000)
    snap(db, inv, d(0), 110000)
    car = post(client, name="Car", target_cents=1000000, target_date=str(d(90)), kind="linked", account_ids=[inv.id]).json()
    assert car["status"] == "behind"
    empty = post(client, name="Empty", target_cents=100, kind="linked", account_ids=[]).json()
    assert (empty["current_cents"], empty["rate_cents"], empty["history_days"]) == (0, None, None)


def test_manual_goal_contributions_rate_and_reach_by(client, db):
    goal = post(client, name="Japan", target_cents=300000, kind="manual").json()
    assert (goal["current_cents"], goal["status"], goal["needed_cents"], goal["rate_cents"]) == (0, "no_date", None, None)
    gid = goal["id"]
    res = client.post(f"/api/goals/{gid}/contributions", json={"date": str(d(-60)), "amount_cents": 60000, "note": "bonus"})
    assert res.status_code == 201
    client.post(f"/api/goals/{gid}/contributions", json={"date": str(d(-10)), "amount_cents": 30000})
    client.post(f"/api/goals/{gid}/contributions", json={"date": str(d(-200)), "amount_cents": 10000})
    goal = goals(client)[0]
    assert goal["current_cents"] == 100000
    assert goal["history_days"] == 90 and goal["rate_cents"] == round(90000 * PER_MONTH / 90)
    assert goal["reach_by"] == str(TODAY + dt.timedelta(days=math.ceil(200000 / goal["rate_cents"] * PER_MONTH)))
    assert [c["amount_cents"] for c in goal["contributions"]] == [30000, 60000, 10000]
    assert goal["contributions"][1]["note"] == "bonus"
    cid = goal["contributions"][0]["id"]
    assert client.delete(f"/api/goals/{gid}/contributions/{cid}").status_code == 204
    assert goals(client)[0]["current_cents"] == 70000


def test_done_status(client, db):
    goal = post(client, name="Small", target_cents=1000, target_date=str(d(30)), kind="manual").json()
    client.post(f"/api/goals/{goal['id']}/contributions", json={"date": str(TODAY), "amount_cents": 1500})
    assert goals(client)[0]["status"] == "done" and goals(client)[0]["needed_cents"] == 0


def test_validation_conflicts_and_not_found(client, db):
    sav = make_account(db, name="Savings", type="savings")
    ok = {"name": "A", "target_cents": 1000, "kind": "linked", "account_ids": [sav.id]}
    assert client.post("/api/goals", json=ok).status_code == 201
    assert client.post("/api/goals", json={**ok, "name": "B"}).status_code == 409
    for bad in (
        {**ok, "name": " "}, {**ok, "target_cents": 0}, {**ok, "target_cents": 10**20}, {**ok, "kind": "other"},
        {**ok, "account_ids": [99999]}, {**ok, "account_ids": [10**20]},
        {"name": "M", "target_cents": 1, "kind": "manual", "account_ids": [sav.id]},
    ):
        assert client.post("/api/goals", json=bad).status_code == 422, bad
    linked_id = goals(client)[0]["id"]
    assert client.post(f"/api/goals/{linked_id}/contributions", json={"date": str(TODAY), "amount_cents": 5}).status_code == 422
    manual = client.post("/api/goals", json={"name": "M", "target_cents": 100, "kind": "manual"}).json()
    for bad in ({"date": str(TODAY), "amount_cents": 0}, {"date": str(TODAY), "amount_cents": 10**20},
                {"date": str(d(1)), "amount_cents": 100}):
        assert client.post(f"/api/goals/{manual['id']}/contributions", json=bad).status_code == 422, bad
    assert client.patch("/api/goals/99999", json={"name": "x"}).status_code == 404
    assert client.delete("/api/goals/99999").status_code == 404
    assert client.delete(f"/api/goals/{manual['id']}/contributions/99999").status_code == 404
    assert client.patch(f"/api/goals/{manual['id']}", json={"account_ids": [sav.id]}).status_code == 422


def test_patch_relinks_clears_date_and_delete_cascades(client, db):
    a = make_account(db, name="A", type="savings")
    b = make_account(db, name="B", type="savings")
    goal = post(client, name="G", target_cents=1000, target_date=str(d(30)), kind="linked", account_ids=[a.id]).json()
    same = client.patch(f"/api/goals/{goal['id']}", json={"account_ids": [a.id]})
    assert same.status_code == 200  # re-saving the same link is not a conflict
    patched = client.patch(f"/api/goals/{goal['id']}", json={"account_ids": [b.id], "target_date": None, "name": "G2"}).json()
    assert ([x["id"] for x in patched["accounts"]], patched["target_date"], patched["name"]) == ([b.id], None, "G2")
    assert post(client, name="H", target_cents=1, kind="linked", account_ids=[a.id]).status_code == 201  # a was freed
    assert client.patch(f"/api/goals/{goal['id']}", json={"account_ids": [a.id]}).status_code == 409
    for bad in ({"name": None}, {"target_cents": None}, {"account_ids": None}):
        assert client.patch(f"/api/goals/{goal['id']}", json=bad).status_code == 422, bad
    assert client.delete(f"/api/goals/{goal['id']}").status_code == 204
    assert post(client, name="I", target_cents=1, kind="linked", account_ids=[b.id]).status_code == 201  # link cascaded


def test_absurdly_far_reach_by_is_null_not_500(client, db):
    res = post(client, name="Big", target_cents=100_000_000, kind="manual")
    gid = res.json()["id"]
    res = client.post(f"/api/goals/{gid}/contributions", json={"date": str(d(-30)), "amount_cents": 100})
    assert res.status_code == 201 and res.json()["reach_by"] is None
    listed = client.get("/api/goals")
    assert listed.status_code == 200 and listed.json()[0]["reach_by"] is None


def test_ninety_day_window_boundaries(client, db):
    sav = make_account(db, name="Savings", type="savings")
    snap(db, sav, d(-91), 1000)
    snap(db, sav, d(-90), 50000)
    snap(db, sav, d(0), 80000)
    goal = post(client, name="Edge", target_cents=500000, kind="linked", account_ids=[sav.id]).json()
    assert goal["history_days"] == 90 and goal["rate_cents"] == round(30000 * PER_MONTH / 90)  # base is d(-90), not d(-91)
    manual = post(client, name="Edge2", target_cents=500000, kind="manual").json()
    for n, cents in ((-91, 7000), (-90, 20000)):
        client.post(f"/api/goals/{manual['id']}/contributions", json={"date": str(d(n)), "amount_cents": cents})
    goal = client.get("/api/goals").json()[1]
    assert goal["current_cents"] == 27000
    assert goal["rate_cents"] == round(20000 * PER_MONTH / 90)  # d(-90) in window, d(-91) out


def test_patch_mixed_relink_keeps_adds_and_drops(client, db):
    a, b, c = (make_account(db, name=n, type="savings") for n in "ABC")
    goal = post(client, name="G", target_cents=1000, kind="linked", account_ids=[a.id, c.id]).json()
    patched = client.patch(f"/api/goals/{goal['id']}", json={"account_ids": [a.id, b.id]})
    assert patched.status_code == 200
    assert sorted(x["id"] for x in patched.json()["accounts"]) == sorted([a.id, b.id])
    assert post(client, name="H", target_cents=1, kind="linked", account_ids=[c.id]).status_code == 201  # c was dropped


def test_name_length_cap(client, db):
    assert post(client, name="x" * 101, target_cents=1, kind="manual").status_code == 422
    goal = post(client, name="x" * 100, target_cents=1, kind="manual").json()
    assert client.patch(f"/api/goals/{goal['id']}", json={"name": "y" * 101}).status_code == 422


def test_concurrent_link_race_is_409_not_500(client, db, monkeypatch):
    from app.models import GoalAccount
    from app.routers import goals as router

    a = make_account(db, name="A", type="savings")
    other = make_account(db, name="B", type="savings")
    first = post(client, name="First", target_cents=1000, kind="linked", account_ids=[a.id]).json()
    mine = post(client, name="Mine", target_cents=1000, kind="linked", account_ids=[other.id]).json()

    # Skip the pre-check, as if another request linked the account after it ran.
    monkeypatch.setattr(router, "_set_accounts", lambda db, goal, ids: setattr(goal, "links", [GoalAccount(account_id=i) for i in ids]))
    assert post(client, name="Race", target_cents=1000, kind="linked", account_ids=[a.id]).status_code == 409
    assert client.patch(f"/api/goals/{mine['id']}", json={"account_ids": [a.id]}).status_code == 409
    monkeypatch.undo()
    assert [g["name"] for g in goals(client)] == ["First", "Mine"]  # nothing half-saved
    assert goals(client)[0]["id"] == first["id"]
