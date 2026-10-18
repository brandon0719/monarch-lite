import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.models import Price, utcnow
from app.services import estimate as est
from app.services import paycheck as pc
from app.services import tax
from tests.conftest import category, make_account, make_txn

TODAY = dt.date.today()
PROFILE = dict(effective_from="2025-03-20", salary_cents=12000000, k401_pct=10, filing_status="single",
               extra_withholding_cents=0, employment_start="2025-03-20")
LUMP = dict(label="Sign-on", kind="lump", amount_cents=2000000, paid_date="2026-01-31")
INST = dict(label="Relocation", kind="installments", amount_cents=2400000, start_date="2026-03-20", end_date="2027-03-20")


def put(client, **kw):
    return client.put("/api/income/profiles", json=PROFILE | kw)


def post(client, **kw):
    return client.post("/api/income/payments", json=kw)


# ---- profiles

def test_put_creates_and_same_effective_from_replaces(client):
    res = put(client)
    assert res.status_code == 200
    first = res.json()
    assert first["salary_cents"] == 12000000 and first["pay_frequency"] == "monthly" and first["id"]
    again = put(client, salary_cents=13000000, k401_pct=5).json()
    assert again["id"] == first["id"] and again["salary_cents"] == 13000000 and again["k401_pct"] == 5
    assert len(client.get("/api/income/profiles").json()) == 1


def test_put_survives_a_concurrent_insert_of_the_same_day(client, monkeypatch):
    first = put(client).json()
    real, calls = Session.scalar, []

    def stale(self, *args, **kw):  # the first lookup misses, as if another request inserted the row just after it
        calls.append(1)
        return None if len(calls) == 1 else real(self, *args, **kw)

    monkeypatch.setattr(Session, "scalar", stale)
    res = put(client, salary_cents=13000000)
    assert res.status_code == 200 and res.json()["id"] == first["id"] and res.json()["salary_cents"] == 13000000
    monkeypatch.undo()
    assert len(client.get("/api/income/profiles").json()) == 1


def test_profiles_list_newest_first(client):
    put(client, effective_from="2025-03-20")
    put(client, effective_from="2026-04-01", salary_cents=13200000)
    put(client, effective_from="2025-09-01", salary_cents=12600000)
    assert [p["effective_from"] for p in client.get("/api/income/profiles").json()] == ["2026-04-01", "2025-09-01", "2025-03-20"]


@pytest.mark.parametrize("patch", [
    dict(salary_cents=0), dict(salary_cents=1_000_000_001), dict(k401_pct=101), dict(k401_pct=-1),
    dict(filing_status="head"), dict(pay_frequency="weekly"), dict(extra_withholding_cents=-1),
    dict(extra_withholding_cents=100_000_001), dict(effective_from="1999-12-31"), dict(employment_start="2101-01-01"),
    dict(effective_from="nope"), dict(salary_cents=None),
])
def test_profile_validation(client, patch):
    assert put(client, **patch).status_code == 422
    assert client.get("/api/income/profiles").json() == []


def test_profile_missing_field_and_bounds_ok(client):
    body = {k: v for k, v in PROFILE.items() if k != "salary_cents"}
    assert client.put("/api/income/profiles", json=body).status_code == 422
    assert put(client, salary_cents=1_000_000_000, k401_pct=100, extra_withholding_cents=100_000_000).status_code == 200


def test_delete_profile_then_404(client):
    pid = put(client).json()["id"]
    assert client.delete(f"/api/income/profiles/{pid}").status_code == 204
    assert client.delete(f"/api/income/profiles/{pid}").status_code == 404
    assert client.delete("/api/income/profiles/0").status_code == 422
    assert client.delete(f"/api/income/profiles/{2**63}").status_code == 422


# ---- payments

def test_post_lump_and_installments(client):
    lump = post(client, **LUMP)
    assert lump.status_code == 201
    assert lump.json() | {"id": 0} == {"id": 0, **LUMP, "start_date": None, "end_date": None, "repay_start": None, "repay_end": None}
    inst = post(client, **INST, repay_start="2026-03-20", repay_end="2028-03-20")
    assert inst.status_code == 201 and inst.json()["repay_end"] == "2028-03-20"
    assert [p["label"] for p in client.get("/api/income/payments").json()] == ["Sign-on", "Relocation"]


@pytest.mark.parametrize("body", [
    {**LUMP, "paid_date": None},                                            # lump needs paid_date
    {**LUMP, "start_date": "2026-01-01", "end_date": "2026-06-01"},         # lump can't carry installment dates
    {**INST, "start_date": None},                                           # installments need both dates
    {**INST, "end_date": None},
    {**INST, "end_date": "2026-03-20"},                                     # start < end
    {**INST, "end_date": "2026-03-19"},
    {**INST, "end_date": "2036-03-21"},                                     # at most 10 years
    {**INST, "paid_date": "2026-01-31"},                                    # installments can't carry paid_date
    {**LUMP, "repay_start": "2026-01-31"},                                  # window needs both
    {**LUMP, "repay_end": "2027-01-31"},
    {**LUMP, "repay_start": "2027-01-31", "repay_end": "2027-01-31"},       # start < end
    {**LUMP, "repay_start": "2027-01-31", "repay_end": "2026-01-31"},
    {**LUMP, "repay_start": "2026-01-31", "repay_end": "2036-02-01"},       # at most 10 years
    {**LUMP, "paid_date": "1999-12-31"}, {**LUMP, "paid_date": "2101-01-01"},
    {**INST, "start_date": "1999-01-01"}, {**INST, "end_date": "2101-01-01"},
    {**LUMP, "repay_start": "1999-01-01", "repay_end": "2000-06-01"},
    {**LUMP, "amount_cents": 0}, {**LUMP, "amount_cents": -5}, {**LUMP, "amount_cents": 1_000_000_001},
    {**LUMP, "label": ""}, {**LUMP, "label": "   "}, {**LUMP, "label": "x" * 101},
    {**LUMP, "kind": "weekly"}, {**LUMP, "paid_date": "not-a-date"},
    {k: v for k, v in LUMP.items() if k != "label"}, {k: v for k, v in LUMP.items() if k != "amount_cents"},
])
def test_payment_validation(client, body):
    assert client.post("/api/income/payments", json=body).status_code == 422
    assert client.get("/api/income/payments").json() == []


def test_payment_boundary_values_accepted(client):
    assert post(client, **(LUMP | {"amount_cents": 1_000_000_000, "paid_date": "2000-01-01"})).status_code == 201
    assert post(client, **(INST | {"start_date": "2026-03-20", "end_date": "2036-03-20"})).status_code == 201
    assert post(client, **LUMP, repay_start="2026-01-31", repay_end="2036-01-31").status_code == 201
    assert post(client, **(LUMP | {"paid_date": "2100-12-31"})).status_code == 201


def test_patch_label_and_explicit_nulls(client):
    pid = post(client, **LUMP).json()["id"]
    res = client.patch(f"/api/income/payments/{pid}", json={"label": "  Bonus "})
    assert res.status_code == 200 and res.json()["label"] == "Bonus"
    for key in ("label", "kind", "amount_cents"):
        assert client.patch(f"/api/income/payments/{pid}", json={key: None}).status_code == 422
    assert client.patch(f"/api/income/payments/{pid}", json={"label": ""}).status_code == 422
    assert client.patch(f"/api/income/payments/{pid}", json={"amount_cents": 0}).status_code == 422
    assert client.get("/api/income/payments").json()[0]["label"] == "Bonus"
    assert client.patch("/api/income/payments/9999", json={"label": "x"}).status_code == 404
    assert client.patch("/api/income/payments/0", json={"label": "x"}).status_code == 422


def test_patch_revalidates_the_merged_row(client):
    lump = post(client, **LUMP).json()["id"]
    inst = post(client, **INST, repay_start="2026-03-20", repay_end="2027-03-20").json()["id"]
    bad = [
        (lump, {"paid_date": None}),                              # lump loses its date
        (lump, {"kind": "installments"}),                         # installments with no window (and a stray paid_date)
        (lump, {"repay_start": "2026-01-31"}),                    # half a window
        (lump, {"repay_start": "2026-01-31", "repay_end": "2026-01-31"}),
        (inst, {"end_date": "2026-03-01"}),                       # end before the stored start
        (inst, {"start_date": "2027-03-20"}),                     # start at the stored end
        (inst, {"end_date": "2036-03-21"}),
        (inst, {"repay_end": None}),                              # clearing one side of the window
        (inst, {"repay_start": "2027-03-20"}),                    # start meets the stored end
        (inst, {"repay_end": "2036-03-21"}),
        (inst, {"start_date": "1999-01-01"}),
        (inst, {"kind": "lump"}),                                 # no paid_date and stray installment dates
    ]
    for pid, patch in bad:
        assert client.patch(f"/api/income/payments/{pid}", json=patch).status_code == 422, patch
    rows = {p["id"]: p for p in client.get("/api/income/payments").json()}
    assert rows[lump]["paid_date"] == "2026-01-31" and rows[lump]["kind"] == "lump" and rows[lump]["repay_start"] is None
    assert (rows[inst]["start_date"], rows[inst]["end_date"], rows[inst]["repay_start"], rows[inst]["repay_end"]) == (
        "2026-03-20", "2027-03-20", "2026-03-20", "2027-03-20")


def test_patch_valid_merges(client):
    inst = post(client, **INST, repay_start="2026-03-20", repay_end="2027-03-20").json()["id"]
    res = client.patch(f"/api/income/payments/{inst}", json={"repay_start": None, "repay_end": None})
    assert res.status_code == 200 and res.json()["repay_start"] is None and res.json()["repay_end"] is None
    res = client.patch(f"/api/income/payments/{inst}", json={"kind": "lump", "paid_date": "2026-05-31", "start_date": None, "end_date": None})
    assert res.status_code == 200 and res.json()["kind"] == "lump" and res.json()["paid_date"] == "2026-05-31"
    res = client.patch(f"/api/income/payments/{inst}", json={"amount_cents": 1, "repay_start": "2026-05-31", "repay_end": "2026-06-30"})
    assert res.status_code == 200 and res.json()["amount_cents"] == 1


def test_delete_payment(client):
    pid = post(client, **LUMP).json()["id"]
    assert client.delete(f"/api/income/payments/{pid}").status_code == 204
    assert client.delete(f"/api/income/payments/{pid}").status_code == 404
    assert client.delete("/api/income/payments/9999").status_code == 404
    assert client.get("/api/income/payments").json() == []


# ---- paychecks

def paychecks(client, year=2026):
    return client.get(f"/api/income/paychecks?year={year}")


def test_paychecks_without_profile(client):
    assert paychecks(client).json() == {"year": 2026, "paychecks": [], "months": [], "monthly_take_home_cents": None,
                                        "tax_year_used": 2026, "tax_year_fallback": False}


def test_paychecks_default_year_is_this_year(client):
    assert client.get("/api/income/paychecks").json()["year"] == TODAY.year


def test_paychecks_year_bounds_and_missing_config(client):
    put(client)
    assert client.get("/api/income/paychecks?year=1999").status_code == 422
    assert client.get("/api/income/paychecks?year=2101").status_code == 422
    assert client.get("/api/income/paychecks?year=abc").status_code == 422
    res = paychecks(client, 2001)  # nothing earlier than 2001 has a config
    assert res.status_code == 404 and res.json()["detail"] == "No tax config for 2001"


def test_paychecks_normal_year_reports_the_year_used(client):
    put(client)
    body = paychecks(client).json()
    assert body["tax_year_used"] == 2026 and body["tax_year_fallback"] is False


def test_paychecks_missing_year_falls_back_to_latest_earlier_config(client, tmp_path, monkeypatch):
    put(client)
    for y in (2024, 2026):
        (tmp_path / f"{y}.yaml").write_text((tax.TAX_DIR / "2026.yaml").read_text().replace("year: 2026", f"year: {y}"))
    monkeypatch.setattr(tax, "TAX_DIR", tmp_path)
    body = paychecks(client, 2027).json()
    assert body["year"] == 2027 and body["tax_year_used"] == 2026 and body["tax_year_fallback"] is True
    assert len(body["paychecks"]) == 12 and body["paychecks"][0]["date"] == "2027-01-31"
    assert body["monthly_take_home_cents"] == 693283
    assert paychecks(client, 2025).json()["tax_year_used"] == 2024
    assert paychecks(client, 2024).json()["tax_year_fallback"] is False
    assert paychecks(client, 2023).status_code == 404
    assert client.get("/api/income/tax-config?year=2027").status_code == 404   # exact-year lookup is unchanged


def test_modeled_paychecks_for_profile(client):
    put(client)
    body = paychecks(client).json()
    assert body["year"] == 2026 and len(body["paychecks"]) == 12 and body["monthly_take_home_cents"] == 693283
    jan = body["paychecks"][0]
    assert (jan["date"], jan["kind"], jan["label"], jan["gross_cents"], jan["net_cents"]) == ("2026-01-31", "regular", "Salary", 1000000, 693283)
    assert jan["lines"] == [{"name": "401(k)", "cents": 100000}, {"name": "Federal withholding", "cents": 124417},
                            {"name": "Social Security", "cents": 62000}, {"name": "Medicare", "cents": 14500},
                            {"name": "WA Cares", "cents": 5800}]
    assert [m["month"] for m in body["months"]] == [f"2026-{m:02d}" for m in range(1, 13)]
    assert body["months"][0] == {"month": "2026-01", "modeled_net_cents": 693283, "actual_cents": 0}


def test_take_home_uses_latest_profile(client):
    put(client)
    put(client, effective_from="2026-07-01", salary_cents=24000000, k401_pct=0)
    ty = tax.load_year(2026)
    latest = pc.Profile(dt.date(2026, 7, 1), 24000000, 0, "single", 0, dt.date(2025, 3, 20))
    assert paychecks(client).json()["monthly_take_home_cents"] == pc.monthly_take_home(latest, ty) != 693283


def test_actual_deposits_visible_accounts_only(client, db):
    put(client)
    visible = make_account(db, name="Checking")
    hidden = make_account(db, name="Old", is_hidden=True)
    pay = category(db, "Paycheck")
    make_txn(db, visible, 690000, dt.date(2026, 1, 31), category_id=pay.id)
    make_txn(db, hidden, 500000, dt.date(2026, 1, 31), category_id=pay.id)                       # hidden account
    make_txn(db, visible, -1000, dt.date(2026, 1, 15), category_id=pay.id)                       # negative
    make_txn(db, visible, 12345, dt.date(2026, 1, 10), category_id=category(db, "Groceries").id)  # other category
    make_txn(db, visible, 777, dt.date(2025, 12, 31), category_id=pay.id)                        # other year
    make_txn(db, visible, 800000, dt.date(2026, 1, 15), category_id=pay.id)
    months = {m["month"]: m for m in paychecks(client).json()["months"]}
    assert months["2026-01"]["actual_cents"] == 1490000 and months["2026-01"]["modeled_net_cents"] == 693283
    assert months["2026-02"]["actual_cents"] == 0


def test_actual_in_month_without_modeled_paycheck(client, db):
    put(client, effective_from="2026-03-01", employment_start="2026-03-01")
    make_txn(db, make_account(db), 690000, dt.date(2026, 1, 31), category_id=category(db, "Paycheck").id)
    months = paychecks(client).json()["months"]
    assert months[0] == {"month": "2026-01", "modeled_net_cents": 0, "actual_cents": 690000}
    assert [m["month"] for m in months][:3] == ["2026-01", "2026-03", "2026-04"]


def test_actual_amount_is_exact_for_single_deposit(client, db):
    put(client)
    hidden = make_account(db, name="Old", is_hidden=True)
    make_txn(db, make_account(db), 690000, dt.date(2026, 1, 31), category_id=category(db, "Paycheck").id)
    make_txn(db, hidden, 100, dt.date(2026, 1, 31), category_id=category(db, "Paycheck").id)
    jan = paychecks(client).json()["months"][0]
    assert (jan["actual_cents"], jan["modeled_net_cents"]) == (690000, 693283)


def test_lump_payment_adds_payment_paycheck(client):
    put(client)
    post(client, **LUMP)
    body = paychecks(client).json()
    on_day = [p for p in body["paychecks"] if p["date"] == "2026-01-31"]
    assert [p["kind"] for p in on_day] == ["regular", "payment"] and on_day[1]["label"] == "Sign-on"
    ty = tax.load_year(2026)
    _, pay_net = pc.payment_paycheck(2000000, ty, 1000000, 0)
    assert on_day[1]["net_cents"] == pay_net and on_day[1]["gross_cents"] == 2000000
    assert body["months"][0]["modeled_net_cents"] == 693283 + pay_net
    assert body["monthly_take_home_cents"] == 693283  # payments never change the regular month
    assert len(body["paychecks"]) == 13


def test_installments_appear_across_years(client):
    put(client)
    post(client, **INST)
    in_2026 = [p for p in paychecks(client).json()["paychecks"] if p["kind"] == "payment"]
    assert [p["date"] for p in in_2026] == [f"2026-{m:02d}-{d}" for m, d in
                                            [(3, 31), (4, 30), (5, 31), (6, 30), (7, 31), (8, 31), (9, 30), (10, 31), (11, 30), (12, 31)]]
    assert sum(p["gross_cents"] for p in in_2026) == 2000000
    assert all(p["gross_cents"] == 200000 for p in in_2026)


# ---- clawback

def test_clawback_items_and_total(client):
    window = dict(repay_start=str(TODAY - dt.timedelta(days=100)), repay_end=str(TODAY - dt.timedelta(days=100) + dt.timedelta(days=365)))
    a = post(client, **LUMP, **window).json()["id"]
    post(client, **LUMP | {"label": "No window"})
    done = post(client, **INST, repay_start="2026-01-01", repay_end="2026-02-01")  # fully earned before today
    assert done.status_code == 201
    body = client.get("/api/income/clawback").json()
    start = TODAY - dt.timedelta(days=100)
    end = start + dt.timedelta(days=365)
    owed = (2000000 * max(0, (end - max(TODAY, start)).days) * 2 + 365) // (2 * 365)  # half-up
    assert body["items"][0] == {"payment_id": a, "label": "Sign-on", "owed_today_cents": owed, "zero_date": str(end)}
    assert len(body["items"]) == 2 and body["items"][1]["owed_today_cents"] == 0
    assert body["total_cents"] == sum(i["owed_today_cents"] for i in body["items"]) == owed


def test_clawback_empty(client):
    assert client.get("/api/income/clawback").json() == {"items": [], "total_cents": 0}


def test_clawback_before_window_owes_everything(client):
    start = TODAY + dt.timedelta(days=30)
    post(client, **LUMP, repay_start=str(start), repay_end=str(start + dt.timedelta(days=100)))
    assert client.get("/api/income/clawback").json()["total_cents"] == 2000000


# ---- tax config

@pytest.mark.parametrize("window", [
    dict(start_date="2026-03-01", end_date="2026-03-15"),
    dict(start_date="2026-03-20", end_date="2026-03-31"),   # the end day is excluded, so no payday remains
    dict(start_date="2026-04-01", end_date="2026-04-30"),
])
def test_installment_window_needs_a_payday(client, window):
    res = post(client, **(INST | window))
    assert res.status_code == 422
    assert client.get("/api/income/payments").json() == []
    pid = post(client, **INST).json()["id"]
    res = client.patch(f"/api/income/payments/{pid}", json=window)
    assert res.status_code == 422 and "at least one payday" in res.json()["detail"]
    assert client.get("/api/income/payments").json()[0]["end_date"] == INST["end_date"]


def test_installment_window_with_one_payday_is_accepted(client):
    assert post(client, **(INST | dict(start_date="2026-03-20", end_date="2026-04-01"))).status_code == 201
    assert post(client, **(INST | dict(start_date="2026-03-31", end_date="2026-04-01"))).status_code == 201


def test_patch_422_detail_has_no_pydantic_prefix(client):
    pid = post(client, **LUMP).json()["id"]
    res = client.patch(f"/api/income/payments/{pid}", json={"paid_date": None})
    assert res.status_code == 422 and res.json()["detail"] == "A lump payment needs a paid date"


def test_real_malformed_yaml_is_a_500_without_a_path(client, tmp_path, monkeypatch):
    put(client)
    (tmp_path / "2026.yaml").write_text("federal: [unclosed\n  - : :\n")
    monkeypatch.setattr(tax, "TAX_DIR", tmp_path)
    for url in ("/api/income/paychecks?year=2026", "/api/income/tax-config?year=2026"):
        res = client.get(url)
        detail = res.json()["detail"]
        assert res.status_code == 500 and detail.startswith("Tax config for 2026 is invalid: 2026.yaml")
        assert str(tmp_path) not in detail and "/" not in detail

def test_tax_config(client):
    res = client.get("/api/income/tax-config?year=2026")
    assert res.status_code == 200 and res.json()["year"] == 2026 and res.json()["fica"]["social_security"]["rate_bp"] == 620
    missing = client.get("/api/income/tax-config?year=2001")
    assert missing.status_code == 404 and missing.json()["detail"] == "No tax config for 2001"
    assert client.get("/api/income/tax-config?year=1999").status_code == 422
    assert client.get("/api/income/tax-config?year=2101").status_code == 422
    assert client.get("/api/income/tax-config").status_code == 422


def test_malformed_tax_config_is_a_clear_500(client, monkeypatch):
    put(client)

    def bad(year):
        raise ValueError("brackets must start at 0")

    monkeypatch.setattr(tax, "load_year", bad)
    for url in ("/api/income/paychecks?year=2026", "/api/income/tax-config?year=2026"):
        res = client.get(url)
        assert res.status_code == 500 and res.json()["detail"] == "Tax config for 2026 is invalid: brackets must start at 0"


# ---- tax estimate and comp projection

BIG = dict(effective_from="2025-01-01", employment_start="2025-01-01", salary_cents=12000000, k401_pct=0)


def vti_price(db, cents=20000):
    db.add(Price(symbol="VTI", price_cents=cents, as_of=utcnow(), source="finnhub"))
    db.commit()


def vest_grant(client, symbol="VTI", shares=1000, vest_date="2026-06-15"):
    return client.post("/api/rsu/grants", json={"label": "Big", "symbol": symbol, "grant_date": "2025-01-01", "start_date": "2025-01-01",
                                                "total_shares": shares, "schedule": "custom",
                                                "vests": [{"vest_date": vest_date, "shares": shares}]})


def test_tax_estimate_without_profile_or_grants(client):
    body = client.get("/api/income/tax-estimate?year=2026").json()
    assert body["has_profile"] is False and body["alert"] is False and body["vests"] == []
    assert body["filing_status"] == "single" and body["tax_year_used"] == 2026 and body["tax_year_fallback"] is False
    cents = [k for k in body if k.endswith("_cents") and k != "threshold_cents"]
    assert cents and all(body[k] == 0 for k in cents)
    assert body["marginal_pct"] == 0 and body["missing_price"] is False


def test_comp_projection_empty(client):
    assert client.get("/api/income/comp-projection").json() == {"growth_pct": 0, "price": None, "years": []}


def test_tax_estimate_with_a_large_vest(client, db):
    put(client, **BIG)
    vti_price(db)
    assert vest_grant(client).status_code == 201
    body = client.get("/api/income/tax-estimate?year=2026").json()
    assert body["balance_cents"] == 1356421 and body["alert"] is True and body["marginal_pct"] == 35
    assert body["has_profile"] is True and body["missing_price"] is False and body["threshold_cents"] == 100000
    assert body["filing_status"] == "single" and body["tax_year_used"] == 2026 and body["tax_year_fallback"] is False
    assert body["vest_income_cents"] == 20000000
    (vest,) = body["vests"]
    assert vest == {"vest_date": "2026-06-15", "grant_label": "Big", "shares": 1000, "value_cents": 20000000,
                    "withheld_cents": 4400000, "shortfall_cents": 2600000}


@pytest.mark.allow_blocked_fetch  # the estimate asks for the unpriced symbol; the stub raises and get_price falls back
def test_tax_estimate_vest_without_a_price(client):
    put(client, **BIG)
    assert vest_grant(client, symbol="NOPE").status_code == 201
    body = client.get("/api/income/tax-estimate?year=2026").json()
    assert body["missing_price"] is True and body["vest_income_cents"] == 0
    (vest,) = body["vests"]
    assert vest["value_cents"] is None and vest["withheld_cents"] is None and vest["shortfall_cents"] is None


def test_tax_estimate_vest_without_a_profile_never_alerts(client, db):
    vti_price(db)
    vest_grant(client)
    body = client.get("/api/income/tax-estimate?year=2026").json()
    assert body["has_profile"] is False and body["alert"] is False
    assert body["vests"][0]["value_cents"] == 20000000


def test_tax_estimate_year_fallback(client):
    put(client, **BIG)
    body = client.get("/api/income/tax-estimate?year=2027").json()
    assert body["year"] == 2027 and body["tax_year_used"] == 2026 and body["tax_year_fallback"] is True


def test_tax_estimate_default_year_and_missing_config(client):
    assert client.get("/api/income/tax-estimate").json()["year"] == TODAY.year
    res = client.get("/api/income/tax-estimate?year=2001")
    assert res.status_code == 404 and res.json()["detail"] == "No tax config for 2001"


def test_comp_projection_years_and_growth(client, db):
    put(client, **BIG)
    vti_price(db)
    vest_grant(client)
    post(client, label="Sign-on", kind="lump", amount_cents=500000, paid_date="2025-06-30")
    body = client.get("/api/income/comp-projection?growth_pct=10").json()
    assert body["growth_pct"] == 10 and body["price"] == {"symbol": "VTI", "price_cents": 20000}
    first, second = body["years"][0], body["years"][1]
    assert [y["year"] for y in body["years"]][:2] == [2025, 2026]
    assert (first["salary_cents"], first["cash_cents"], first["rsu_shares"], first["rsu_cents"]) == (12000000, 500000, 0, 0)
    assert first["total_cents"] == 12500000
    rsu = est.rsu_value(1000, 20000, 10, 2026 - TODAY.year)
    assert second["rsu_shares"] == 1000 and second["rsu_cents"] == rsu
    assert second["total_cents"] == second["salary_cents"] + second["cash_cents"] + rsu


@pytest.mark.allow_blocked_fetch  # the projection asks for the unpriced symbol; the stub raises and get_price falls back
def test_comp_projection_without_a_price(client):
    put(client, **BIG)
    vest_grant(client, symbol="NOPE")
    body = client.get("/api/income/comp-projection").json()
    assert body["price"] is None
    year = next(y for y in body["years"] if y["year"] == 2026)
    assert year["rsu_shares"] == 1000 and year["rsu_cents"] is None and year["total_cents"] is None
    assert next(y for y in body["years"] if y["year"] == 2025)["total_cents"] == 12000000


@pytest.mark.parametrize("url", [
    "/api/income/comp-projection?growth_pct=-51", "/api/income/comp-projection?growth_pct=101",
    "/api/income/comp-projection?growth_pct=abc", "/api/income/tax-estimate?year=1999",
    "/api/income/tax-estimate?year=2101", "/api/income/tax-estimate?year=abc",
])
def test_estimate_bounds(client, url):
    assert client.get(url).status_code == 422


def test_comp_projection_bounds_ok(client):
    for g in (-50, 100):
        assert client.get(f"/api/income/comp-projection?growth_pct={g}").status_code == 200


# ---- fix round 1

def test_comp_projection_range_follows_the_spec(client, db):
    put(client, **BIG)
    vti_price(db)
    vest_grant(client, vest_date="2029-06-15")
    post(client, label="Early", kind="lump", amount_cents=1, paid_date="2025-02-28")
    body = client.get("/api/income/comp-projection").json()
    assert [y["year"] for y in body["years"]] == list(range(2025, 2030))   # employment start .. last vest
    assert body["years"][-1]["rsu_shares"] == 1000


def test_comp_projection_without_profile_starts_at_the_first_vest(client, db):
    vti_price(db)
    vest_grant(client, vest_date="2031-06-15")
    years = [y["year"] for y in client.get("/api/income/comp-projection").json()["years"]]
    assert years == [2031]   # today's year doesn't lower the start; nothing else extends the end


def test_comp_projection_far_future_vest_at_max_growth_does_not_overflow(client, db):
    vti_price(db)
    vest_grant(client, vest_date="2100-12-31")
    r = client.get("/api/income/comp-projection?growth_pct=100")
    assert r.status_code == 200 and r.json()["years"][-1]["year"] == 2100


def test_comp_projection_clamps_out_of_range_vests(client, db):
    from app.models import RsuGrant, RsuVest
    put(client, **BIG)
    vti_price(db)
    grant = RsuGrant(label="Bad", symbol="VTI", grant_date=dt.date(2025, 1, 1), start_date=dt.date(2025, 1, 1),
                     total_shares=2, schedule="custom",
                     vests=[RsuVest(vest_date=dt.date(9999, 12, 31), shares=1), RsuVest(vest_date=dt.date(1, 1, 1), shares=1)])
    db.add(grant)
    db.commit()
    body = client.get("/api/income/comp-projection").json()
    assert body["years"][0]["year"] == 2000 and body["years"][-1]["year"] == 2100 and len(body["years"]) == 101


def test_filing_status_falls_back_to_the_earliest_profile(client):
    put(client, **(BIG | {"effective_from": "2027-01-01", "employment_start": "2027-01-01", "filing_status": "married_jointly"}))
    body = client.get("/api/income/tax-estimate?year=2026").json()
    assert body["has_profile"] is True and body["filing_status"] == "married_jointly"


def test_no_profile_with_vests_pins_the_zeros(client, db):
    vti_price(db)
    vest_grant(client)
    body = client.get("/api/income/tax-estimate?year=2026").json()
    zero = ["wages_cents", "pretax_cents", "vest_income_cents", "taxable_cents", "liability_cents", "withheld_salary_cents",
            "withheld_supplemental_cents", "withheld_vests_cents", "withheld_cents", "balance_cents", "marginal_pct"]
    assert all(body[k] == 0 for k in zero) and body["alert"] is False and body["has_profile"] is False
    assert body["vests"][0]["value_cents"] == 20000000 and body["vests"][0]["withheld_cents"] == 4400000
    assert body["vests"][0]["shortfall_cents"] is None   # no salary model, so no meaningful marginal rate


@pytest.mark.parametrize("patch", [
    dict(grant_date="1999-12-31"), dict(grant_date="2101-01-01"), dict(start_date="1999-12-31"), dict(start_date="9999-01-01"),
    dict(schedule="custom", total_shares=10, vests=[{"vest_date": "9999-12-31", "shares": 10}]),
    dict(schedule="custom", total_shares=10, vests=[{"vest_date": "1999-12-31", "shares": 10}]),
    dict(schedule="semiannual", total_shares=10, count=2, first_vest="2101-01-01"),
    dict(schedule="semiannual", total_shares=10, count=2, first_vest="1999-12-31"),
    dict(schedule="semiannual", total_shares=10, count=3, first_vest="2100-01-15"),   # generated vests run past 2100
    dict(start_date="2100-06-01"),                                                      # amazon vests land in 2101+
])
def test_grant_dates_are_bounded(client, patch):
    base = {"label": "G", "symbol": "VTI", "grant_date": "2025-01-01", "start_date": "2025-01-01", "total_shares": 100,
            "schedule": "amazon_5_15_40_40"}
    assert client.post("/api/rsu/grants", json=base | patch).status_code == 422
    assert client.get("/api/rsu").json()["grants"] == []


def test_replace_vests_dates_are_bounded(client):
    g = vest_grant(client).json()
    res = client.put(f"/api/rsu/grants/{g['id']}/vests", json={"vests": [{"vest_date": "9999-12-31", "shares": 1000}]})
    assert res.status_code == 422


def test_grant_boundary_dates_accepted(client):
    base = {"label": "G", "symbol": "VTI", "grant_date": "2000-01-01", "start_date": "2000-01-01", "total_shares": 10,
            "schedule": "custom", "vests": [{"vest_date": "2000-01-01", "shares": 5}, {"vest_date": "2100-12-31", "shares": 5}]}
    assert client.post("/api/rsu/grants", json=base).status_code == 201
