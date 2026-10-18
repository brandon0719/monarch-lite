import datetime as dt

import pytest

from sqlalchemy import func, select

from app.models import Price, RsuVest
from app.models import utcnow

AMAZON = {"label": "New-hire grant", "symbol": "vti", "grant_date": "2025-03-01", "start_date": "2025-03-20",
          "total_shares": 400, "schedule": "amazon_5_15_40_40"}


def price(db, symbol="VTI", cents=25000):
    db.add(Price(symbol=symbol, price_cents=cents, as_of=utcnow(), source="finnhub"))
    db.commit()


def test_create_amazon_grant_and_get_with_values(client, db):
    today = dt.date.today()
    price(db)
    # Starting today makes every vest upcoming (the first is on the 15th of next year's anniversary month).
    res = client.post("/api/rsu/grants", json={**AMAZON, "grant_date": today.isoformat(), "start_date": today.isoformat()})
    assert res.status_code == 201
    grant = res.json()
    assert grant["symbol"] == "VTI" and [v["shares"] for v in grant["vests"]] == [20, 60, 80, 80, 80, 80]
    body = client.get("/api/rsu").json()
    assert body["price"] == {"symbol": "VTI", "price_cents": 25000, "as_of": body["price"]["as_of"], "source": "finnhub"}
    (g,) = body["grants"]
    vested = sum(v["shares"] for v in g["vests"] if dt.date.fromisoformat(v["vest_date"]) <= today)
    assert g["vested_shares"] == vested and g["unvested_shares"] == 400 - vested
    assert g["unvested_value_cents"] == (400 - vested) * 25000
    assert all(v["value_cents"] == v["shares"] * 25000 for v in g["vests"])
    upcoming = [v for v in g["vests"] if not v["vested"]]
    assert upcoming and vested == 0
    assert body["totals"]["next_vest"]["vest_date"] == upcoming[0]["vest_date"]
    assert body["totals"]["next_vest"]["grant_label"] == "New-hire grant"


@pytest.mark.allow_blocked_fetch  # GET asks for the unpriced symbol; the stub raises and get_price falls back
def test_values_are_null_without_a_price(client, db):
    client.post("/api/rsu/grants", json={**AMAZON, "symbol": "NOPE"})
    body = client.get("/api/rsu").json()
    assert body["price"] is None and body["grants"][0]["unvested_value_cents"] is None
    assert all(v["value_cents"] is None for v in body["grants"][0]["vests"])


def test_semiannual_and_custom_grants(client, db):
    semi = client.post("/api/rsu/grants", json={**AMAZON, "label": "Refresher", "schedule": "semiannual",
                                                "first_vest": "2027-05-15", "count": 4, "total_shares": 10}).json()
    assert [v["shares"] for v in semi["vests"]] == [2, 2, 2, 4]
    custom = client.post("/api/rsu/grants", json={**AMAZON, "label": "Custom", "schedule": "custom", "total_shares": 10,
                                                  "vests": [{"vest_date": "2027-01-15", "shares": 4}, {"vest_date": "2026-07-15", "shares": 6}]}).json()
    assert [v["vest_date"] for v in custom["vests"]] == ["2026-07-15", "2027-01-15"]
    res = client.put(f"/api/rsu/grants/{custom['id']}/vests", json={"vests": [{"vest_date": "2028-01-15", "shares": 10}]})
    assert res.status_code == 200 and [v["shares"] for v in res.json()["vests"]] == [10]
    assert client.put(f"/api/rsu/grants/{semi['id']}/vests", json={"vests": [{"vest_date": "2028-01-15", "shares": 10}]}).status_code == 422


def test_validation_patch_delete_and_cascade(client, db):
    for bad in ({**AMAZON, "label": " "}, {**AMAZON, "total_shares": 0}, {**AMAZON, "total_shares": 10**7},
                {**AMAZON, "schedule": "monthly"}, {**AMAZON, "symbol": "X" * 17},
                {**AMAZON, "schedule": "semiannual"}, {**AMAZON, "schedule": "custom"},
                {**AMAZON, "schedule": "custom", "total_shares": 10, "vests": [{"vest_date": "2027-01-15", "shares": 9}]}):
        assert client.post("/api/rsu/grants", json=bad).status_code == 422, bad
    g = client.post("/api/rsu/grants", json=AMAZON).json()
    patched = client.patch(f"/api/rsu/grants/{g['id']}", json={"label": "Sign-on", "external_id": "G-1"}).json()
    assert (patched["label"], patched["external_id"]) == ("Sign-on", "G-1")
    assert client.patch(f"/api/rsu/grants/{g['id']}", json={"label": None}).status_code == 422
    assert client.patch("/api/rsu/grants/99999", json={"label": "x"}).status_code == 404
    assert client.patch(f"/api/rsu/grants/{10**20}", json={"label": "x"}).status_code == 422
    assert client.delete(f"/api/rsu/grants/{g['id']}").status_code == 204
    db.expire_all()
    assert db.scalar(select(func.count(RsuVest.id))) == 0
    assert client.delete(f"/api/rsu/grants/{g['id']}").status_code == 404


def test_empty(client):
    assert client.get("/api/rsu").json() == {"price": None, "grants": [], "totals": {
        "unvested_shares": 0, "unvested_value_cents": None, "vested_shares": 0, "next_vest": None}}


def iso(days):
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


def custom(label, symbol, vests, grant_date="2025-01-01"):
    return {**AMAZON, "label": label, "symbol": symbol, "grant_date": grant_date, "schedule": "custom",
            "total_shares": sum(s for _, s in vests), "vests": [{"vest_date": iso(d), "shares": s} for d, s in vests]}


def test_amzn_price_next_vest_and_today_boundary_across_grants(client, db):
    price(db, "VTI", 25000)
    price(db, "AMZN", 20000)
    client.post("/api/rsu/grants", json=custom("First", "VTI", [(0, 2), (30, 3)]))
    client.post("/api/rsu/grants", json=custom("Second", "AMZN", [(10, 4), (400, 1)], grant_date="2025-06-01"))
    body = client.get("/api/rsu").json()
    assert body["price"]["symbol"] == "AMZN" and body["price"]["price_cents"] == 20000
    first, second = body["grants"]
    assert [v["vested"] for v in first["vests"]] == [True, False]  # a vest dated today counts as vested
    assert (first["vested_shares"], first["unvested_shares"]) == (2, 3)
    assert body["totals"]["next_vest"] == {"vest_date": iso(10), "shares": 4, "value_cents": 4 * 20000,
                                           "grant_label": "Second"}
    assert body["totals"]["unvested_shares"] == 8 and body["totals"]["vested_shares"] == 2
    assert body["totals"]["unvested_value_cents"] == 3 * 25000 + 5 * 20000


def test_first_symbol_is_the_price_without_amzn(client, db):
    price(db, "VTI", 25000)
    price(db, "BND", 7000)
    client.post("/api/rsu/grants", json=custom("A", "VTI", [(5, 1)]))
    client.post("/api/rsu/grants", json=custom("B", "BND", [(5, 1)], grant_date="2025-06-01"))
    assert client.get("/api/rsu").json()["price"]["symbol"] == "VTI"


@pytest.mark.allow_blocked_fetch
def test_fully_vested_unpriced_grant_does_not_null_the_total(client, db):
    price(db, "VTI", 25000)
    client.post("/api/rsu/grants", json=custom("Old", "OLD", [(-10, 5)]))
    client.post("/api/rsu/grants", json=custom("Live", "VTI", [(30, 3), (400, 7)], grant_date="2025-06-01"))
    old, live = client.get("/api/rsu").json()["grants"]
    assert old["unvested_shares"] == 0 and old["unvested_value_cents"] == 0
    assert live["unvested_value_cents"] == 10 * 25000
    assert client.get("/api/rsu").json()["totals"]["unvested_value_cents"] == 10 * 25000


@pytest.mark.allow_blocked_fetch
def test_total_is_null_when_a_grant_with_unvested_shares_is_unpriced(client, db):
    price(db, "VTI", 25000)
    client.post("/api/rsu/grants", json=custom("Priced", "VTI", [(30, 3)]))
    client.post("/api/rsu/grants", json=custom("Unpriced", "OLD", [(30, 2)], grant_date="2025-06-01"))
    totals = client.get("/api/rsu").json()["totals"]
    assert totals["unvested_shares"] == 5 and totals["unvested_value_cents"] is None


def test_mutations_never_fetch_and_use_the_cache_even_when_stale(client, db):
    # No allow_blocked_fetch mark: the autouse guard fails this test if POST/PATCH/PUT reach Finnhub.
    stale = Price(symbol="VTI", price_cents=25000, as_of=utcnow() - dt.timedelta(hours=5), source="finnhub")
    db.add(stale)
    db.commit()
    created = client.post("/api/rsu/grants", json=custom("Stale", "VTI", [(30, 3)]))
    assert created.json()["unvested_value_cents"] == 3 * 25000
    gid = created.json()["id"]
    assert client.patch(f"/api/rsu/grants/{gid}", json={"label": "Renamed"}).json()["unvested_value_cents"] == 75000
    put = client.put(f"/api/rsu/grants/{gid}/vests", json={"vests": [{"vest_date": iso(60), "shares": 3}]})
    assert put.json()["unvested_value_cents"] == 75000
    unpriced = client.post("/api/rsu/grants", json=custom("None", "NOPE", [(30, 3)]))
    assert unpriced.status_code == 201 and unpriced.json()["unvested_value_cents"] is None
