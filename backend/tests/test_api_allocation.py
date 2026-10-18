import datetime as dt

from app.models import AssetClass, Holding
from tests.conftest import make_account

TODAY = dt.date.today()
TARGETS = {"stocks_pct": 80, "bonds_pct": 15, "cash_pct": 5, "drift_threshold": 5}


def add(db, account, symbol, value, description="Fund"):
    db.add(Holding(account_id=account.id, symbol=symbol, description=description, shares="1",
                   market_value_cents=value, cost_basis_cents=None, as_of=TODAY))
    db.commit()


def test_allocation_unconfigured_then_with_targets_and_override(client, db):
    inv = make_account(db, name="Brokerage", type="investment")
    add(db, inv, "VTI", 90000)
    add(db, inv, "BND", 5000, "Bond ETF")
    add(db, inv, "QSWEEP", 5000, "Deposit Sweep Account")
    body = client.get("/api/allocation").json()
    assert body["configured"] is False and body["total_cents"] == 100000
    assert [(c["asset_class"], c["value_cents"], c["pct"], c["target_pct"]) for c in body["classes"]] == [
        ("stocks", 95000, 0.95, None), ("bonds", 0, 0.0, None), ("cash", 5000, 0.05, None)]
    res = client.put("/api/holdings/classes/BND", json={"asset_class": "bonds"})
    assert res.status_code == 200 and res.json() == {"symbol": "BND", "asset_class": "bonds"}
    assert client.put("/api/allocation/targets", json=TARGETS).status_code == 200
    body = client.get("/api/allocation").json()
    stocks, bonds, cash = body["classes"]
    assert (stocks["pct"], stocks["drift_pts"], stocks["over"]) == (0.9, 10.0, True)
    assert (bonds["pct"], bonds["drift_pts"], bonds["over"]) == (0.05, -10.0, True)
    assert (cash["drift_pts"], cash["over"]) == (0.0, False)
    assert [h["asset_class"] for h in client.get("/api/holdings").json() if h["symbol"] == "BND"] == ["bonds"]


def test_targets_get_put_and_validation(client):
    assert client.get("/api/allocation/targets").json() == {
        "configured": False, "stocks_pct": None, "bonds_pct": None, "cash_pct": None, "drift_threshold": 5}
    assert client.put("/api/allocation/targets", json=TARGETS).json() == {"configured": True, **TARGETS}
    for bad in ({**TARGETS, "stocks_pct": 81}, {**TARGETS, "cash_pct": -1}, {**TARGETS, "drift_threshold": 0},
                {**TARGETS, "drift_threshold": 51}, {**TARGETS, "stocks_pct": 10**20}):
        assert client.put("/api/allocation/targets", json=bad).status_code == 422, bad
    res = client.put("/api/allocation/targets", json={**TARGETS, "stocks_pct": 81})
    assert "must add up to 100%" in str(res.json()["detail"])


def test_class_override_validation(client):
    assert client.put("/api/holdings/classes/VTI", json={"asset_class": "gold"}).status_code == 422
    assert client.put(f"/api/holdings/classes/{'X' * 33}", json={"asset_class": "cash"}).status_code == 422
    assert client.put("/api/holdings/classes/%20", json={"asset_class": "cash"}).status_code == 422


def test_empty_allocation(client):
    body = client.get("/api/allocation").json()
    assert body["total_cents"] == 0 and [c["pct"] for c in body["classes"]] == [0.0, 0.0, 0.0]


def test_drift_is_over_only_beyond_the_threshold(client, db):
    inv = make_account(db, name="Brokerage", type="investment")
    add(db, inv, "VTI", 85000)
    add(db, inv, "QSWEEP", 15000, "Deposit Sweep Account")
    targets = {"stocks_pct": 80, "bonds_pct": 0, "cash_pct": 20, "drift_threshold": 5}

    def classes(**kw):
        client.put("/api/allocation/targets", json={**targets, **kw})
        body = client.get("/api/allocation").json()
        return body["drift_threshold"], [(c["drift_pts"], c["over"]) for c in body["classes"]]

    assert classes() == (5, [(5.0, False), (0.0, False), (-5.0, False)])            # exactly +-threshold is not over
    assert classes(drift_threshold=4) == (4, [(5.0, True), (0.0, False), (-5.0, True)])
    assert classes(drift_threshold=50)[1] == [(5.0, False), (0.0, False), (-5.0, False)]


def test_class_override_slash_symbol_and_repeat_put(client, db):
    inv = make_account(db, name="Brokerage", type="investment")
    add(db, inv, "BRK/B", 1000)
    res = client.put("/api/holdings/classes/BRK%2FB", json={"asset_class": "bonds"})
    assert res.status_code == 200 and res.json() == {"symbol": "BRK/B", "asset_class": "bonds"}
    assert client.get("/api/holdings").json()[0]["asset_class"] == "bonds"
    assert client.put("/api/holdings/classes/BRK%2FB", json={"asset_class": "cash"}).json()["asset_class"] == "cash"
    assert client.get("/api/holdings").json()[0]["asset_class"] == "cash"
    assert db.query(AssetClass).count() == 1       # the second PUT updated the row


def test_default_threshold_when_unconfigured(client):
    assert client.get("/api/allocation").json()["drift_threshold"] == 5
