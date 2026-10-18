import datetime as dt

from app.services import estimate as est
from app.services import paycheck as pc
from tests.test_tax import TY

D = dt.date


def profile(start):
    return pc.Profile(start, 12000000, 0, "single", 0, start)


def test_part_year_with_sign_on_is_a_refund():
    lump = pc.Payment(1, "Sign-on", "lump", 5000000, D(2025, 9, 30), None, None, None, None)
    rows = pc.build_year([profile(D(2025, 9, 15))], [lump], TY, 2025)
    r = est.year_estimate(rows, [], "single", TY)
    assert (r["wages_cents"], r["taxable_cents"], r["liability_cents"]) == (8533333, 6923333, 994333)
    assert (r["withheld_salary_cents"], r["withheld_supplemental_cents"], r["withheld_vests_cents"]) == (485084, 1100000, 0)
    assert (r["withheld_cents"], r["balance_cents"], r["marginal_pct"]) == (1585084, -590751, 22)
    assert r["alert"] is False and r["missing_price"] is False and r["vests"] == []


def test_large_vest_owes_and_alerts():
    rows = pc.build_year([profile(D(2025, 1, 1))], [], TY, 2026)
    r = est.year_estimate(rows, [est.VestEvent(D(2026, 6, 15), "Grant", 1000, 20000000)], "single", TY)
    assert (r["vest_income_cents"], r["taxable_cents"], r["liability_cents"]) == (20000000, 30390000, 7513425)
    assert (r["withheld_salary_cents"], r["withheld_vests_cents"], r["withheld_cents"]) == (1757004, 4400000, 6157004)
    assert (r["balance_cents"], r["marginal_pct"], r["alert"]) == (1356421, 35, True)
    assert r["vests"] == [{"vest_date": D(2026, 6, 15), "grant_label": "Grant", "shares": 1000,
                           "value_cents": 20000000, "withheld_cents": 4400000, "shortfall_cents": 2600000}]


def test_supplemental_million_split_spans_payment_then_vest_and_missing_price():
    bonus = pc.Payment(2, "Bonus", "lump", 90000000, D(2026, 3, 31), None, None, None, None)
    rows = pc.build_year([profile(D(2025, 1, 1))], [bonus], TY, 2026)
    vests = [est.VestEvent(D(2026, 6, 15), "Grant", 1000, 20000000), est.VestEvent(D(2026, 9, 15), "Grant", 5, None)]
    r = est.year_estimate(rows, vests, "single", TY)
    assert r["vests"][0]["withheld_cents"] == 5900000 and r["vests"][0]["shortfall_cents"] == 1500000  # $100k at 22% + $100k at 37%
    assert r["vests"][1] == {"vest_date": D(2026, 9, 15), "grant_label": "Grant", "shares": 5,
                             "value_cents": None, "withheld_cents": None, "shortfall_cents": None}
    assert r["missing_price"] is True and r["vest_income_cents"] == 20000000


def test_marginal_pct_boundaries():
    b = TY.brackets["single"]
    assert est.marginal_pct(0, b) == 0 and est.marginal_pct(1240000, b) == 10 and est.marginal_pct(1240001, b) == 12


def test_rsu_value_growth_and_null_price():
    assert est.rsu_value(22, 25000, 0, 1) == 550000
    assert est.rsu_value(88, 25000, 10, 3) == 2928200          # 88 x $250 x 1.1^3
    assert est.rsu_value(10, 25000, -20, 2) == 160000
    assert est.rsu_value(10, 25000, 10, -1) == 250000          # past years: no growth applied
    assert est.rsu_value(88, None, 10, 3) is None
    assert est.rsu_value(1000, 20000, 100, 74) == 20000 * 1000 * 2 ** 74   # exact integer math, no Decimal overflow


def test_same_day_payment_is_withheld_before_the_vest():
    bonus = pc.Payment(3, "Bonus", "lump", 90000000, D(2026, 6, 15), None, None, None, None)
    rows = pc.build_year([profile(D(2025, 1, 1))], [bonus], TY, 2026)
    r = est.year_estimate(rows, [est.VestEvent(D(2026, 6, 15), "Grant", 10, 20000000)], "single", TY)
    assert r["vests"][0]["withheld_cents"] == 5900000   # $100k at 22% + $100k at 37%: the $900k bonus counts first


def test_unpriced_vest_that_is_not_last_does_not_advance_ytd_supplemental():
    bonus = pc.Payment(4, "Bonus", "lump", 90000000, D(2026, 3, 31), None, None, None, None)
    rows = pc.build_year([profile(D(2025, 1, 1))], [bonus], TY, 2026)
    vests = [est.VestEvent(D(2026, 5, 1), "Grant", 5, None), est.VestEvent(D(2026, 6, 15), "Grant", 1000, 20000000)]
    r = est.year_estimate(rows, vests, "single", TY)
    assert r["vests"][0]["withheld_cents"] is None
    assert r["vests"][1]["withheld_cents"] == 5900000                    # same split as if the unpriced vest were absent


def test_shortfall_is_clamped_at_zero_when_withholding_exceeds_marginal():
    low = pc.Profile(D(2025, 1, 1), 2400000, 0, "single", 0, D(2025, 1, 1))   # $24k salary: 10% bracket
    rows = pc.build_year([low], [], TY, 2026)
    r = est.year_estimate(rows, [est.VestEvent(D(2026, 6, 15), "Grant", 1, 100000)], "single", TY)
    assert r["marginal_pct"] == 10                                               # 10% of $1,000 = $100 < $220 withheld
    assert r["vests"][0]["withheld_cents"] == 22000 and r["vests"][0]["shortfall_cents"] == 0


def test_balance_equal_to_threshold_does_not_alert():
    rows = pc.build_year([profile(D(2025, 1, 1))], [], TY, 2026)
    base = est.year_estimate(rows, [], "single", TY)["balance_cents"]
    old = est.ALERT_THRESHOLD_CENTS
    try:
        est.ALERT_THRESHOLD_CENTS = base
        assert est.year_estimate(rows, [], "single", TY)["alert"] is False
        est.ALERT_THRESHOLD_CENTS = base - 1
        assert est.year_estimate(rows, [], "single", TY)["alert"] is True
    finally:
        est.ALERT_THRESHOLD_CENTS = old
