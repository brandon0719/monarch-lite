import datetime as dt

from app.services import paycheck as pc
from tests.test_tax import TY

D = dt.date


def profile(**kw):
    base = dict(effective_from=D(2025, 3, 20), salary_cents=12000000, k401_pct=10, filing_status="single",
                extra_withholding_cents=0, employment_start=D(2025, 3, 20))
    return pc.Profile(**(base | kw))


def payment(**kw):
    base = dict(id=1, label="Bonus", kind="lump", amount_cents=100000, paid_date=None, start_date=None,
                end_date=None, repay_start=None, repay_end=None)
    return pc.Payment(**(base | kw))


def test_regular_paycheck_lines_and_net():
    lines, net = pc.regular_paycheck(1000000, profile(), TY, ytd_before=0)
    assert lines == [{"name": "401(k)", "cents": 100000}, {"name": "Federal withholding", "cents": 124417},
                     {"name": "Social Security", "cents": 62000}, {"name": "Medicare", "cents": 14500},
                     {"name": "WA Cares", "cents": 5800}]
    assert net == 1000000 - 306717
    assert pc.monthly_take_home(profile(), TY) == net


def test_payment_paycheck_uses_supplemental_rate_and_no_401k():
    lines, net = pc.payment_paycheck(5000000, TY, ytd_before=0, ytd_supp_before=0)
    assert lines[0] == {"name": "Federal withholding (supplemental)", "cents": 1100000}
    assert "401(k)" not in [l["name"] for l in lines]
    assert net == 5000000 - sum(l["cents"] for l in lines)


def test_paydays_and_first_month_proration():
    assert pc.paydays(D(2025, 3, 20), D(2025, 6, 15)) == [D(2025, 3, 31), D(2025, 4, 30), D(2025, 5, 31)]
    p = profile()
    assert pc.regular_gross(p, D(2025, 3, 31), D(2025, 3, 20)) == 387097    # 12 of 31 days of $10,000
    assert pc.regular_gross(p, D(2025, 4, 30), D(2025, 3, 20)) == 1000000


def test_profile_on_effective_dating():
    a, b = profile(), profile(effective_from=D(2025, 9, 1), salary_cents=13200000)
    assert pc.profile_on([a, b], D(2025, 8, 31)) is a and pc.profile_on([a, b], D(2025, 9, 30)) is b
    assert pc.profile_on([a, b], D(2025, 3, 1)) is None


def test_installments_split_with_remainder_last():
    days = pc.paydays(D(2025, 1, 1), D(2027, 12, 31))
    pay = payment(kind="installments", amount_cents=2400005, start_date=D(2026, 3, 20), end_date=D(2027, 3, 20))
    got = pc.installment_amounts(pay, days)
    assert [d for d, _ in got][0] == D(2026, 3, 31) and [d for d, _ in got][-1] == D(2027, 2, 28)
    assert [c for _, c in got] == [200000] * 11 + [200005]


def test_build_year_resets_ytd_and_crosses_ss_wage_base():
    p = profile(salary_cents=30000000, k401_pct=0, employment_start=D(2025, 6, 1), effective_from=D(2025, 6, 1))
    rows = pc.build_year([p], [], TY, 2026)
    assert [r["date"] for r in rows][:2] == [D(2026, 1, 31), D(2026, 2, 28)] and len(rows) == 12
    ss = [next(l["cents"] for l in r["lines"] if l["name"] == "Social Security") for r in rows]
    assert ss[0] == 155000 and ss[7] == 58900 and ss[8] == 0      # base reached in August


def test_build_year_orders_regular_before_payment_and_labels():
    p = profile()
    lump = payment(label="Sign-on (year 1)", amount_cents=5000000, paid_date=D(2025, 3, 31))
    rows = pc.build_year([p], [lump], TY, 2025)
    assert [(r["date"], r["kind"]) for r in rows][:2] == [(D(2025, 3, 31), "regular"), (D(2025, 3, 31), "payment")]
    assert rows[1]["label"] == "Sign-on (year 1)" and rows[1]["gross_cents"] == 5000000


def test_clawback_daily_proration():
    pay = payment(amount_cents=3650000, paid_date=D(2025, 1, 15), repay_start=D(2025, 1, 1), repay_end=D(2026, 1, 1))
    assert pc.clawback_owed(pay, D(2024, 12, 1)) == 3650000
    assert pc.clawback_owed(pay, D(2025, 7, 2)) == 1830000          # 183 of 365 days left
    assert pc.clawback_owed(pay, D(2026, 1, 1)) == 0 and pc.clawback_owed(pay, D(2027, 1, 1)) == 0
    assert pc.clawback_owed(payment(), D(2025, 7, 2)) is None        # no repay window


def test_long_installment_window_divides_by_all_paydays():
    p = profile(employment_start=D(2025, 1, 1), effective_from=D(2025, 1, 1))
    pay = payment(kind="installments", amount_cents=3600000, start_date=D(2025, 1, 1), end_date=D(2030, 1, 1))
    rows = [r for r in pc.build_year([p], [pay], TY, 2025) if r["kind"] == "payment"]
    assert len(rows) == 12 and all(r["gross_cents"] == 60000 for r in rows)      # 60 paydays, not 36


def test_bad_rows_degrade_instead_of_raising():
    assert pc.installment_amounts(payment(kind="installments", start_date=D(2025, 1, 1), end_date=None), [D(2025, 1, 31)]) == []
    same = payment(repay_start=D(2025, 1, 1), repay_end=D(2025, 1, 1))
    flipped = payment(repay_start=D(2025, 2, 1), repay_end=D(2025, 1, 1))
    assert pc.clawback_owed(same, D(2025, 1, 1)) is None and pc.clawback_owed(flipped, D(2025, 1, 1)) is None


def test_proration_edges_and_month_end_window():
    p = profile()
    assert pc.regular_gross(p, D(2025, 4, 30), D(2025, 4, 1)) == 1000000           # start on the 1st: full month
    assert pc.regular_gross(p, D(2025, 4, 30), D(2025, 4, 30)) == 33333             # last day: 1 of 30
    days = pc.paydays(D(2025, 1, 1), D(2025, 12, 31))
    pay = payment(kind="installments", amount_cents=300000, start_date=D(2025, 1, 31), end_date=D(2025, 4, 30))
    assert [d for d, _ in pc.installment_amounts(pay, days)] == [D(2025, 1, 31), D(2025, 2, 28), D(2025, 3, 31)]


def test_paydays_before_the_earliest_profile_use_the_earliest_profile():
    p = profile(employment_start=D(2025, 3, 20), effective_from=D(2025, 6, 1))
    rows = pc.build_year([p], [], TY, 2025)
    assert rows[0]["date"] == D(2025, 3, 31) and rows[0]["label"] == "Salary"
    assert rows[0]["gross_cents"] == 387097 and len(rows) == 10   # March prorated 12/31, then Apr..Dec
    assert rows[1]["gross_cents"] == 1000000
