import datetime as dt

from tests.conftest import category, make_account, make_txn

TODAY = dt.date.today()
THIS = TODAY.replace(day=1)
PREV = (THIS - dt.timedelta(days=1)).replace(day=1)
PREV2 = (PREV - dt.timedelta(days=1)).replace(day=1)


def ym(d):
    return d.strftime("%Y-%m")


def configure(client):
    client.put("/api/budget/settings", json={"take_home_cents": 700000, "needs_pct": 50,
                                             "wants_pct": 30, "savings_pct": 20})


def test_unconfigured_still_lists_months_newest_first(client):
    body = client.get("/api/budget").json()
    assert body["configured"] is False and body["base_cents"] is None and body["targets"] is None
    assert [m["month"] for m in body["months"]] == [ym(THIS), ym(PREV), ym(PREV2)]
    assert body["months"][0]["is_current"] and not body["months"][1]["is_current"]


def test_targets_and_bucket_actuals(client, db):
    configure(client)
    acct = make_account(db)
    hidden = make_account(db, name="Hidden", is_hidden=True)
    make_txn(db, acct, -5000, THIS, category_id=category(db, "Groceries").id)
    make_txn(db, acct, 1000, THIS, category_id=category(db, "Groceries").id)  # refund nets out
    make_txn(db, acct, -3000, THIS, category_id=category(db, "Shopping").id)
    make_txn(db, acct, -100000, THIS, category_id=category(db, "Rent").id)
    make_txn(db, acct, -7777, PREV, category_id=category(db, "Shopping").id)
    make_txn(db, hidden, -9999, THIS, category_id=category(db, "Shopping").id)
    body = client.get("/api/budget", params={"months": 2}).json()
    assert body["configured"] is True and body["base_cents"] == 700000
    assert body["targets"] == {"needs": 350000, "wants": 210000, "savings": 140000}
    cur, prev = body["months"]
    assert (cur["needs_cents"], cur["wants_cents"]) == (104000, 3000)
    assert "rent_actual_cents" not in cur
    assert prev["wants_cents"] == 7777


def test_savings_rule(client, db):
    chk = make_account(db, type="checking")
    sav = make_account(db, name="Savings", type="savings")
    card = make_account(db, name="Card", type="credit")
    inv1 = make_account(db, name="Brokerage", type="investment")
    inv2 = make_account(db, name="Brokerage 2", type="investment")
    transfer = category(db, "Transfer").id

    def pair(a, amount_a, b):
        t1, t2 = make_txn(db, a, amount_a, THIS), make_txn(db, b, -amount_a, THIS)
        t1.transfer_pair_id, t2.transfer_pair_id = t2.id, t1.id
        t1.category_id = t2.category_id = transfer
        db.commit()
        return t1

    pair(chk, -50000, sav)                                    # +500 moved to savings
    pair(chk, 20000, sav)                                     # -200 pulled back out
    make_txn(db, chk, -100000, THIS, category_id=category(db, "Savings Transfer").id)  # +1000 external
    make_txn(db, sav, 30000, THIS, category_id=category(db, "Savings Transfer").id)    # savings-side leg: ignored
    pair(chk, -12000, card)                                   # card payment: ignored
    pair(inv1, -5000, inv2)                                   # sweep: ignored
    t = pair(chk, -40000, inv1)                               # +400, user-categorized: counted once
    t.category_id, t.category_source = category(db, "Investment Contribution").id, "user"
    db.commit()
    mislabelled = pair(chk, -9000, sav)                       # paired, but tagged as spending: not counted at all
    mislabelled.category_id = category(db, "Groceries").id
    db.commit()
    body = client.get("/api/budget", params={"months": 1}).json()
    assert body["months"][0]["savings_cents"] == 50000 - 20000 + 100000 + 40000


def test_cashflow(client, db):
    acct = make_account(db)
    make_txn(db, acct, 500000, THIS, category_id=category(db, "Paycheck").id)
    make_txn(db, acct, 10000, THIS, category_id=category(db, "Other Income").id)
    make_txn(db, acct, -200000, THIS, category_id=category(db, "Rent").id)
    make_txn(db, acct, -5000, THIS)  # uncategorized outflow is spending
    make_txn(db, acct, -300000, THIS, category_id=category(db, "Savings Transfer").id)  # not spending
    make_txn(db, acct, -1000, PREV, category_id=category(db, "Dining").id)
    body = client.get("/api/cashflow", params={"months": 2}).json()
    cur, prev = body["months"]
    assert cur == {"month": ym(THIS), "income_cents": 510000, "spent_cents": 205000,
                   "saved_cents": 305000, "savings_rate": round(305000 / 510000, 4)}
    assert prev["income_cents"] == 0 and prev["saved_cents"] == -1000 and prev["savings_rate"] is None
    assert body["average_savings_rate"] == round(305000 / 510000, 4)


def test_month_param_bounds(client):
    assert client.get("/api/budget", params={"months": 0}).status_code == 422
    assert client.get("/api/budget", params={"months": 25}).status_code == 422
    assert client.get("/api/cashflow", params={"months": 37}).status_code == 422


def test_budget_returns_settings(client):
    assert client.get("/api/budget").json()["take_home_cents"] is None
    configure(client)
    body = client.get("/api/budget").json()
    assert body["take_home_cents"] == 700000 and "rent_cents" not in body
    assert (body["needs_pct"], body["wants_pct"], body["savings_pct"]) == (50, 30, 20)


def test_cashflow_average_is_weighted_not_mean_of_rates(client, db):
    acct = make_account(db)
    make_txn(db, acct, 100000, THIS, category_id=category(db, "Paycheck").id)
    make_txn(db, acct, -50000, THIS, category_id=category(db, "Dining").id)       # rate 0.5 on 1000
    make_txn(db, acct, 900000, PREV, category_id=category(db, "Paycheck").id)
    make_txn(db, acct, -90000, PREV, category_id=category(db, "Dining").id)       # rate 0.9 on 9000
    body = client.get("/api/cashflow", params={"months": 2}).json()
    assert [m["savings_rate"] for m in body["months"]] == [0.5, 0.9]
    assert body["average_savings_rate"] == round((50000 + 810000) / 1000000, 4) == 0.86  # mean of rates would be 0.7


def test_month_boundaries_each_land_in_their_own_month(client, db):
    acct = make_account(db)
    last_of_prev, first_of_this = THIS - dt.timedelta(days=1), THIS
    dining = category(db, "Dining").id
    make_txn(db, acct, -1100, last_of_prev, category_id=dining)
    make_txn(db, acct, -2200, first_of_this, category_id=dining)
    cur, prev = client.get("/api/budget", params={"months": 2}).json()["months"]
    assert (cur["needs_cents"], prev["needs_cents"]) == (2200, 1100)
    cash = client.get("/api/cashflow", params={"months": 2}).json()["months"]
    assert (cash[0]["spent_cents"], cash[1]["spent_cents"]) == (2200, 1100)


def test_last_months_wraps_year():
    from app.services.budget import last_months
    assert last_months(dt.date(2026, 1, 15), 3) == ["2026-01", "2025-12", "2025-11"]


def test_hidden_accounts_excluded_from_savings_income_and_cashflow(client, db):
    hidden = make_account(db, name="Hidden", is_hidden=True)
    hidden_sav = make_account(db, name="Hidden Sav", type="savings", is_hidden=True)
    t1 = make_txn(db, hidden, -40000, THIS)
    t2 = make_txn(db, hidden_sav, 40000, THIS)
    t1.transfer_pair_id, t2.transfer_pair_id = t2.id, t1.id
    make_txn(db, hidden, -5000, THIS, category_id=category(db, "Savings Transfer").id)
    make_txn(db, hidden, 800000, THIS, category_id=category(db, "Paycheck").id)
    make_txn(db, hidden, -7000, THIS, category_id=category(db, "Dining").id)
    db.commit()
    assert client.get("/api/budget", params={"months": 1}).json()["months"][0]["savings_cents"] == 0
    cash = client.get("/api/cashflow", params={"months": 1}).json()
    assert cash["months"][0]["income_cents"] == 0 and cash["months"][0]["spent_cents"] == 0
    assert cash["average_savings_rate"] is None


def test_cashflow_months_zero_is_422(client):
    assert client.get("/api/cashflow", params={"months": 0}).status_code == 422


def test_other_bucket_counts_as_spent_but_not_in_meters(client, db):
    acct = make_account(db)
    payoff = client.post("/api/categories", json={"name": "Loan Payoff", "group_name": "One-off", "bucket": "other"})
    assert payoff.status_code in (200, 201)
    make_txn(db, acct, -1_000_000, THIS, category_id=payoff.json()["id"])
    make_txn(db, acct, -5000, THIS, category_id=category(db, "Groceries").id)
    cur = client.get("/api/budget", params={"months": 1}).json()["months"][0]
    assert (cur["needs_cents"], cur["wants_cents"]) == (5000, 0)
    cash = client.get("/api/cashflow", params={"months": 1}).json()["months"][0]
    overview = client.get("/api/overview", params={"month": ym(THIS)}).json()
    assert cash["spent_cents"] == overview["spent_cents"] == 1_005_000
