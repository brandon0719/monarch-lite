import datetime as dt

from app.models import BalanceSnapshot
from app.services.recurring import step
from tests.conftest import category, make_account, make_txn

TODAY = dt.date.today()
START = (TODAY - dt.timedelta(days=100)).replace(day=10)  # day 10: no month-end clamping
RECENT = TODAY - dt.timedelta(days=70)  # three monthly charges from here end within ~10 days of today: still running


def d(days):
    return str(TODAY + dt.timedelta(days=days))


def get(client):
    return client.get("/api/recurring").json()


def add(client, **kw):
    body = {"merchant": "Spotify", "amount_cents": -1899, "cadence": "monthly", "anchor_date": d(3)} | kw
    return client.post("/api/recurring/items", json=body)


def test_item_crud_and_validation(client, db):
    res = add(client)
    assert res.status_code == 201
    item = res.json()
    assert item["name"] == "Spotify" and item["next_due"] == item["anchor_date"] == d(3)
    assert item["status"] == "upcoming" and item["last_date"] is None and item["last_amount_cents"] is None
    patched = client.patch(f"/api/recurring/items/{item['id']}", json={"name": "Music", "amount_cents": -2099}).json()
    assert (patched["name"], patched["amount_cents"]) == ("Music", -2099)
    for bad in ({"merchant": "  "}, {"amount_cents": 0}, {"cadence": "daily"}, {"category_id": 99999}, {"name": " "}):
        assert add(client, **bad).status_code == 422, bad
    for bad in ({"amount_cents": 0}, {"merchant": None}, {"category_id": 99999}):
        assert client.patch(f"/api/recurring/items/{item['id']}", json=bad).status_code == 422, bad
    assert client.patch("/api/recurring/items/99999", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/recurring/items/{item['id']}").status_code == 204
    assert client.delete(f"/api/recurring/items/{item['id']}").status_code == 404
    assert get(client)["items"] == []


def test_matching_payment_advances_next_due_and_late_status(client, db):
    acct, hidden = make_account(db), make_account(db, name="Hidden", is_hidden=True)
    anchor = TODAY - dt.timedelta(days=40)
    add(client, anchor_date=str(anchor))
    make_txn(db, hidden, -1899, anchor + dt.timedelta(days=1), merchant="Spotify")  # hidden: ignored
    make_txn(db, acct, -5000, anchor, merchant="Spotify")                           # >10% off: ignored
    make_txn(db, acct, -1950, anchor + dt.timedelta(days=2), merchant="Spotify")
    (item,) = get(client)["items"]
    assert item["next_due"] == str(step(anchor, "monthly", 1))
    assert item["status"] == "late"
    assert (item["last_amount_cents"], item["last_date"]) == (-1950, str(anchor + dt.timedelta(days=2)))


def test_suggestions_alerts_confirm_and_dismiss(client, db):
    acct = make_account(db)
    subs = category(db, "Subscriptions").id
    for k in range(3):
        make_txn(db, acct, -1899, step(RECENT, "monthly", k), merchant="Spotify", category_id=subs)
        make_txn(db, acct, -500, step(RECENT, "monthly", k), merchant="Gym")
    body = get(client)
    assert {s["merchant"] for s in body["suggestions"]} == {"Spotify", "Gym"}
    assert {a["merchant"] for a in body["alerts"] if a["kind"] == "new_recurring"} == {"Spotify", "Gym"}
    res = client.post("/api/recurring/suggestions/confirm", json={"merchant": "Spotify"})
    assert res.status_code == 201
    item = res.json()
    assert (item["merchant"], item["name"], item["amount_cents"], item["cadence"]) == ("Spotify", "Spotify", -1899, "monthly")
    assert item["anchor_date"] == str(step(RECENT, "monthly", 3)) and item["category_id"] == subs
    assert client.post("/api/recurring/suggestions/dismiss", json={"merchant": "Gym"}).status_code == 204
    assert client.post("/api/recurring/suggestions/dismiss", json={"merchant": "Gym"}).status_code == 204
    after = get(client)
    assert after["suggestions"] == [] and [a for a in after["alerts"] if a["kind"] == "new_recurring"] == []
    assert client.post("/api/recurring/suggestions/confirm", json={"merchant": "Nope"}).status_code == 404


def test_detection_skips_excluded_hidden_blank_and_tracked(client, db):
    acct, hidden = make_account(db), make_account(db, name="Hidden", is_hidden=True)
    transfer = category(db, "Transfer").id
    for k in range(3):
        day = step(RECENT, "monthly", k)
        make_txn(db, acct, -10000, day, merchant="Savings Move", category_id=transfer)
        make_txn(db, hidden, -1500, day, merchant="Hidden Sub")
        make_txn(db, acct, -999, day, merchant="Tracked")
        make_txn(db, acct, -300, day, merchant="")
    add(client, merchant="Tracked", amount_cents=-999)
    assert get(client)["suggestions"] == []


def test_price_increase_alert_only_when_latest_is_higher(client, db):
    acct = make_account(db)
    spotify = add(client, anchor_date=str(START)).json()
    add(client, merchant="Netflix", amount_cents=-1500, anchor_date=str(START))
    second = step(START, "monthly", 1)
    make_txn(db, acct, -1899, START, merchant="Spotify")
    make_txn(db, acct, -1999, second, merchant="Spotify")
    make_txn(db, acct, -1500, START, merchant="Netflix")
    make_txn(db, acct, -1400, second, merchant="Netflix")
    alerts = [a for a in get(client)["alerts"] if a["kind"] == "price_increase"]
    assert alerts == [{"kind": "price_increase", "item_id": spotify["id"], "name": "Spotify",
                       "previous_cents": -1899, "latest_cents": -1999, "date": str(second)}]


def test_upcoming_rows_running_balance_and_totals(client, db):
    chk = make_account(db, type="checking")
    sav = make_account(db, name="Savings", type="savings")
    closed = make_account(db, name="Old", type="checking", closed_at=TODAY - dt.timedelta(days=1))
    db.add_all([
        BalanceSnapshot(account_id=chk.id, date=TODAY - dt.timedelta(days=2), balance_cents=100000),
        BalanceSnapshot(account_id=chk.id, date=TODAY - dt.timedelta(days=1), balance_cents=50000),
        BalanceSnapshot(account_id=sav.id, date=TODAY, balance_cents=999999),
        BalanceSnapshot(account_id=closed.id, date=TODAY, balance_cents=777),
    ])
    db.commit()
    add(client, merchant="Rent", amount_cents=-120000, anchor_date=d(5))
    add(client, merchant="Paycheck", amount_cents=300000, anchor_date=d(10))
    add(client, merchant="Gym", amount_cents=-2500, cadence="weekly", anchor_date=d(1))
    up = client.get("/api/recurring/upcoming", params={"days": 14}).json()
    assert up["start_balance_cents"] == 50000
    assert [(r["name"], r["date"]) for r in up["rows"]] == [("Gym", d(1)), ("Rent", d(5)), ("Gym", d(8)), ("Paycheck", d(10))]
    assert [r["balance_cents"] for r in up["rows"]] == [47500, -72500, -75000, 225000]
    assert (up["bills_cents"], up["income_cents"]) == (125000, 300000)


def test_upcoming_without_checking_and_late_item_once(client, db):
    add(client, merchant="Late Bill", amount_cents=-1000, cadence="weekly", anchor_date=d(-10))
    up = client.get("/api/recurring/upcoming", params={"days": 7}).json()
    assert up["start_balance_cents"] is None
    assert [r["date"] for r in up["rows"]] == [d(-10), d(4)]
    assert all(r["balance_cents"] is None for r in up["rows"])
    assert client.get("/api/recurring/upcoming", params={"days": 0}).status_code == 422
    assert client.get("/api/recurring/upcoming", params={"days": 91}).status_code == 422


def test_category_delete_nulls_item_category(client, db):
    created = client.post("/api/categories", json={"name": "Streaming", "group_name": "Lifestyle", "bucket": "wants"}).json()
    add(client, category_id=created["id"])
    client.delete(f"/api/categories/{created['id']}", params={"replacement_id": category(db, "Shopping").id})
    db.expire_all()
    assert get(client)["items"][0]["category_id"] is None


def test_oversized_ints_are_422_not_500(client, db):
    big = 10**20
    for bad in ({"amount_cents": big}, {"amount_cents": -big}, {"category_id": big}):
        assert add(client, **bad).status_code == 422, bad
    item = add(client).json()
    for bad in ({"amount_cents": big}, {"amount_cents": -big}, {"category_id": big}):
        assert client.patch(f"/api/recurring/items/{item['id']}", json=bad).status_code == 422, bad


def test_patch_nulls_and_clearing_category(client, db):
    subs = category(db, "Subscriptions").id
    item = add(client, category_id=subs).json()
    assert item["category_id"] == subs
    for field in ("name", "amount_cents", "cadence", "anchor_date"):
        res = client.patch(f"/api/recurring/items/{item['id']}", json={field: None})
        assert res.status_code == 422, field
    res = client.patch(f"/api/recurring/items/{item['id']}", json={"category_id": None})
    assert res.status_code == 200 and res.json()["category_id"] is None


def test_price_increase_alert_fires_beyond_ten_percent(client, db):
    acct = make_account(db)
    item = add(client, anchor_date=str(START)).json()
    second = step(START, "monthly", 1)
    make_txn(db, acct, -1899, START, merchant="Spotify")
    make_txn(db, acct, -2099, second, merchant="Spotify")  # +10.5%: outside the match window, still alerts
    make_txn(db, acct, 5000, second, merchant="Spotify")  # refund: other sign, ignored
    alerts = [a for a in get(client)["alerts"] if a["kind"] == "price_increase"]
    assert alerts == [{"kind": "price_increase", "item_id": item["id"], "name": "Spotify",
                       "previous_cents": -1899, "latest_cents": -2099, "date": str(second)}]


def test_confirm_category_ignores_non_matching_latest_transaction(client, db):
    acct = make_account(db)
    subs, transfer = category(db, "Subscriptions").id, category(db, "Transfer").id
    for k in range(3):
        make_txn(db, acct, -1899, step(RECENT, "monthly", k), merchant="Spotify", category_id=subs)
    make_txn(db, acct, -9000, step(RECENT, "monthly", 2) + dt.timedelta(days=1), merchant="Spotify", category_id=transfer)  # later, other amount
    res = client.post("/api/recurring/suggestions/confirm", json={"merchant": "Spotify"})
    assert res.status_code == 201 and res.json()["category_id"] == subs


def _price_alerts(client):
    return [a for a in get(client)["alerts"] if a["kind"] == "price_increase"]


def test_income_item_gets_no_price_alert(client, db):
    acct = make_account(db)
    add(client, merchant="Paycheck", amount_cents=300000, anchor_date=str(START))
    make_txn(db, acct, 300000, START, merchant="Paycheck")
    make_txn(db, acct, 320000, step(START, "monthly", 1), merchant="Paycheck")
    assert _price_alerts(client) == []


def test_tiny_non_matching_earlier_charge_is_not_a_previous_price(client, db):
    acct = make_account(db)
    add(client, merchant="Utility", amount_cents=-5000, anchor_date=str(START))
    make_txn(db, acct, -1, START, merchant="Utility")
    make_txn(db, acct, -500000, step(START, "monthly", 1), merchant="Utility")
    assert _price_alerts(client) == []


def test_zero_amount_charge_neither_hides_nor_causes_an_alert(client, db):
    acct = make_account(db)
    item = add(client, anchor_date=str(START)).json()
    second, third = step(START, "monthly", 1), step(START, "monthly", 2)
    make_txn(db, acct, -1899, START, merchant="Spotify")
    make_txn(db, acct, 0, second, merchant="Spotify")
    assert _price_alerts(client) == []  # zero alone is not a rise
    make_txn(db, acct, -2099, third, merchant="Spotify")
    assert _price_alerts(client) == [{"kind": "price_increase", "item_id": item["id"], "name": "Spotify",
                                      "previous_cents": -1899, "latest_cents": -2099, "date": str(third)}]
    make_txn(db, acct, 0, third + dt.timedelta(days=1), merchant="Spotify")  # a later zero does not hide it
    assert len(_price_alerts(client)) == 1


def _upcoming(client, days=30):
    return client.get("/api/recurring/upcoming", params={"days": days}).json()


def test_grace_period_before_late(client, db):
    recent = add(client, merchant="Recent", amount_cents=-1000, anchor_date=d(-3)).json()
    old = add(client, merchant="Old", amount_cents=-1000, anchor_date=d(-6)).json()
    assert (recent["status"], old["status"]) == ("upcoming", "late")
    rows = _upcoming(client)["rows"]
    by_item = {}
    for row in rows:
        by_item.setdefault(row["item_id"], []).append(row)
    assert [r["late"] for r in by_item[recent["id"]]] == [False, False]
    assert by_item[recent["id"]][0]["date"] == d(-3)
    assert [r["late"] for r in by_item[old["id"]]] == [True, False]
    assert by_item[old["id"]][0]["date"] == d(-6)


def test_payment_posting_late_each_cycle_is_never_late_and_listed_once(client, db):
    acct = make_account(db)
    anchor = TODAY - dt.timedelta(days=70)
    item = add(client, merchant="Rent", amount_cents=-100000, anchor_date=str(anchor)).json()
    for k in range(3):
        make_txn(db, acct, -100000, step(anchor, "monthly", k) + dt.timedelta(days=8), merchant="Rent")
    (got,) = get(client)["items"]
    assert got["status"] == "upcoming" and got["next_due"] == str(step(anchor, "monthly", 3))
    rows = _upcoming(client)["rows"]
    assert [(r["item_id"], r["date"], r["late"]) for r in rows] == [(item["id"], str(step(anchor, "monthly", 3)), False)]


def test_missed_old_cycle_followed_by_payments_does_not_pin_next_due(client, db):
    acct = make_account(db)
    anchor = TODAY - dt.timedelta(days=125)
    add(client, merchant="Water", amount_cents=-4000, anchor_date=str(anchor))
    for k in (0, 2, 3, 4):  # cycle 1 never paid
        make_txn(db, acct, -4000, step(anchor, "monthly", k), merchant="Water")
    (got,) = get(client)["items"]
    assert got["next_due"] == str(step(anchor, "monthly", 5)) and got["status"] == "upcoming"
    assert [r["date"] for r in _upcoming(client)["rows"]] == [got["next_due"]]


def test_stale_series_is_not_suggested_and_active_one_is(client, db):
    acct = make_account(db)
    for ago in (130, 100, 70):  # cancelled: next charge was due ~40 days ago
        make_txn(db, acct, -999, TODAY - dt.timedelta(days=ago), merchant="Cancelled")
    for ago in (60, 30, 2):
        make_txn(db, acct, -1299, TODAY - dt.timedelta(days=ago), merchant="Active")
    body = get(client)
    assert [s["merchant"] for s in body["suggestions"]] == ["Active"]
    assert [a["merchant"] for a in body["alerts"] if a["kind"] == "new_recurring"] == ["Active"]


def test_suggestion_hidden_only_once_next_date_is_over_five_days_old(client, db):
    acct = make_account(db)
    for ago in (26, 19, 12):  # weekly, last 12 days ago: next date is exactly 5 days ago, still shown
        make_txn(db, acct, -500, TODAY - dt.timedelta(days=ago), merchant="Edge")
    for ago in (27, 20, 13):  # next date 6 days ago: hidden
        make_txn(db, acct, -700, TODAY - dt.timedelta(days=ago), merchant="TooOld")
    assert [s["merchant"] for s in get(client)["suggestions"]] == ["Edge"]


def test_shared_merchant_price_alert_ignores_the_other_items_charge(client, db):
    acct = make_account(db)
    add(client, merchant="Amazon", name="Prime", amount_cents=-1499, anchor_date=str(START))
    music = add(client, merchant="Amazon", name="Music", amount_cents=-999, anchor_date=str(START)).json()
    second = step(START, "monthly", 1)
    make_txn(db, acct, -999, START, merchant="Amazon")
    make_txn(db, acct, -1499, START, merchant="Amazon")
    make_txn(db, acct, -999, second, merchant="Amazon")
    make_txn(db, acct, -1499, second + dt.timedelta(days=1), merchant="Amazon")  # Prime posts last
    assert [a for a in _price_alerts(client) if a["item_id"] == music["id"]] == []
    assert _price_alerts(client) == []


# ---- paycheck items follow the latest normal deposit
PROFILE = dict(effective_from="2025-03-20", salary_cents=12000000, k401_pct=10, filing_status="single",
               extra_withholding_cents=0, employment_start="2025-03-20")


def paycheck_item(client, **kw):
    return add(client, merchant="Northwind Payroll", name="Paycheck", amount_cents=500000,
               anchor_date=d(14), follows_paycheck=True, **kw)


def take_home(client):
    return client.get("/api/income/paychecks").json()["monthly_take_home_cents"]


def test_follows_paycheck_only_for_income(client, db):
    assert add(client, follows_paycheck=True).status_code == 422            # a bill can't follow a paycheck
    item = paycheck_item(client).json()
    assert item["follows_paycheck"] is True
    assert client.patch(f"/api/recurring/items/{item['id']}", json={"amount_cents": -100}).status_code == 422
    assert client.patch(f"/api/recurring/items/{item['id']}", json={"follows_paycheck": None}).status_code == 422
    plain = add(client).json()
    assert plain["follows_paycheck"] is False
    assert client.patch(f"/api/recurring/items/{plain['id']}", json={"follows_paycheck": True}).status_code == 422


def test_paycheck_amount_is_latest_normal_deposit_skipping_outliers(client, db):
    client.put("/api/income/profiles", json=PROFILE)
    ref = take_home(client)
    acct, hidden = make_account(db), make_account(db, name="Hidden", is_hidden=True)
    item = paycheck_item(client).json()
    assert item["amount_cents"] == ref                                       # no deposits yet: the modeled take-home
    make_txn(db, acct, ref - 1000, TODAY - dt.timedelta(days=45), merchant="Northwind Payroll")
    make_txn(db, acct, ref + 2000, TODAY - dt.timedelta(days=16), merchant="Northwind Payroll")
    make_txn(db, acct, ref * 4, TODAY - dt.timedelta(days=15), merchant="Northwind Payroll")   # sign-on month: skipped
    make_txn(db, hidden, ref + 9, TODAY - dt.timedelta(days=5), merchant="Northwind Payroll")  # hidden: ignored
    (got,) = get(client)["items"]
    assert got["amount_cents"] == ref + 2000
    assert (got["last_amount_cents"], got["last_date"]) == (ref + 2000, d(-16))
    rows = client.get("/api/recurring/upcoming?days=30").json()["rows"]
    assert [r["amount_cents"] for r in rows] == [ref + 2000]


def test_paycheck_amount_falls_back_to_model_when_every_deposit_is_an_outlier(client, db):
    client.put("/api/income/profiles", json=PROFILE)
    ref = take_home(client)
    make_txn(db, make_account(db), ref * 4, TODAY - dt.timedelta(days=15), merchant="Northwind Payroll")
    paycheck_item(client)
    assert get(client)["items"][0]["amount_cents"] == ref


def test_paycheck_without_profile_uses_latest_deposit_then_saved_amount(client, db):
    item = paycheck_item(client).json()
    assert item["amount_cents"] == 500000                                    # no profile, no deposits: as saved
    make_txn(db, make_account(db), 612345, TODAY - dt.timedelta(days=15), merchant="Northwind Payroll")
    assert get(client)["items"][0]["amount_cents"] == 612345                 # no model to judge outliers: as paid


def test_outlier_boundary_is_25_percent_and_follow_can_be_toggled(client, db):
    client.put("/api/income/profiles", json=PROFILE)
    ref = take_home(client)
    acct = make_account(db)
    make_txn(db, acct, ref + ref // 4, TODAY - dt.timedelta(days=40), merchant="Northwind Payroll")       # exactly 25%: kept
    make_txn(db, acct, ref + ref // 4 + 1, TODAY - dt.timedelta(days=10), merchant="Northwind Payroll")   # just over: skipped
    item = paycheck_item(client).json()
    assert item["amount_cents"] == ref + ref // 4
    off = client.patch(f"/api/recurring/items/{item['id']}", json={"follows_paycheck": False, "amount_cents": 700000}).json()
    assert (off["follows_paycheck"], off["amount_cents"]) == (False, 700000)
    assert client.patch(f"/api/recurring/items/{item['id']}", json={"follows_paycheck": True, "amount_cents": -5}).status_code == 422
    on = client.patch(f"/api/recurring/items/{item['id']}", json={"follows_paycheck": True}).json()
    assert (on["follows_paycheck"], on["amount_cents"]) == (True, ref + ref // 4)


def test_no_tax_config_uses_latest_deposit(client, db, monkeypatch):
    client.put("/api/income/profiles", json=PROFILE)
    from app.services import tax
    monkeypatch.setattr(tax, "load_year", lambda year: None)
    monkeypatch.setattr(tax, "years_before", lambda year: [])
    make_txn(db, make_account(db), 2900000, TODAY - dt.timedelta(days=15), merchant="Northwind Payroll")
    paycheck_item(client)
    assert get(client)["items"][0]["amount_cents"] == 2900000                # no model to judge outliers: as paid
