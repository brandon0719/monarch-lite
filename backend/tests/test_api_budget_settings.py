from app.models import BudgetSettings

OK = {"take_home_cents": 730000, "needs_pct": 50, "wants_pct": 30, "savings_pct": 20}


def test_defaults_when_unset_and_get_never_writes(client, db):
    assert client.get("/api/budget/settings").json() == {
        "take_home_cents": None, "needs_pct": 50, "wants_pct": 30, "savings_pct": 20,
    }
    assert db.get(BudgetSettings, 1) is None


def test_put_then_get_and_upsert(client):
    assert client.put("/api/budget/settings", json=OK).json() == OK
    assert client.get("/api/budget/settings").json() == OK
    changed = {**OK, "needs_pct": 60, "wants_pct": 20}
    assert client.put("/api/budget/settings", json=changed).json() == changed
    assert client.get("/api/budget/settings").json() == changed


def test_validation(client):
    for bad in (
        {**OK, "wants_pct": 31},                    # sums to 101
        {**OK, "take_home_cents": 0},
        {**OK, "needs_pct": 101, "wants_pct": -1},
    ):
        assert client.put("/api/budget/settings", json=bad).status_code == 422, bad


def test_rent_is_no_longer_a_setting(client):
    assert client.put("/api/budget/settings", json={**OK, "rent_cents": 1}).json() == OK


def test_rejected_put_leaves_settings_unchanged(client):
    client.put("/api/budget/settings", json=OK)
    assert client.put("/api/budget/settings", json={**OK, "wants_pct": 31}).status_code == 422
    assert client.get("/api/budget/settings").json() == OK


def test_bad_split_message(client):
    res = client.put("/api/budget/settings", json={**OK, "wants_pct": 31})
    assert "must add up to 100%" in str(res.json()["detail"])
