"""Year tax estimate and total-comp projection (M5 R3 spec). Pure functions; integer cents."""
import datetime as dt
from dataclasses import dataclass

from . import tax
from .tax import TaxYear, half_up_div

ALERT_THRESHOLD_CENTS = 100000  # $1,000


@dataclass(frozen=True)
class VestEvent:
    vest_date: dt.date
    grant_label: str
    shares: int
    value_cents: int | None


def marginal_pct(taxable: int, brackets: list[tuple[int, int]]) -> int:
    """Rate of the bracket containing `taxable`; 0 when nothing is taxable."""
    if taxable <= 0:
        return 0
    return [rate for lower, rate in brackets if lower < taxable][-1]


def _sum_lines(rows: list[dict], name: str) -> int:
    return sum(line["cents"] for row in rows for line in row["lines"] if line["name"] == name)


def year_estimate(rows: list[dict], vests: list[VestEvent], filing: str, ty: TaxYear) -> dict:
    """Projected federal income tax for a year vs. modeled withholding (salary, supplemental, vests)."""
    wages = sum(r["gross_cents"] for r in rows)
    pretax = _sum_lines(rows, "401(k)")
    # Vests are supplemental wages: withhold in date order after payments (same day: payments first).
    events = sorted([(r["date"], 0, r["gross_cents"], None) for r in rows if r["kind"] == "payment"]
                    + [(v.vest_date, 1, v.value_cents, i) for i, v in enumerate(vests)],
                    key=lambda e: (e[0], e[1]))
    ytd_supp, vest_wh = 0, {}
    for _, _, cents, idx in events:
        if cents is None:
            continue
        if idx is not None:
            vest_wh[idx] = tax.federal_supplemental(cents, ytd_supp, ty)
        ytd_supp += cents
    vest_income = sum(v.value_cents for v in vests if v.value_cents is not None)
    taxable = max(0, wages - pretax + vest_income - ty.standard_deduction[filing])
    liability = tax.bracket_tax(taxable, ty.brackets[filing])
    salary_wh = _sum_lines(rows, "Federal withholding")
    supp_wh = _sum_lines(rows, "Federal withholding (supplemental)")
    vests_wh = sum(vest_wh.values())
    withheld = salary_wh + supp_wh + vests_wh
    marginal = marginal_pct(taxable, ty.brackets[filing])
    vest_rows = []
    for i, v in enumerate(vests):
        wh = vest_wh.get(i)
        short = None if v.value_cents is None else max(0, half_up_div(v.value_cents * marginal, 100) - wh)
        vest_rows.append({"vest_date": v.vest_date, "grant_label": v.grant_label, "shares": v.shares,
                          "value_cents": v.value_cents, "withheld_cents": wh, "shortfall_cents": short})
    balance = liability - withheld
    return {
        "wages_cents": wages, "pretax_cents": pretax, "vest_income_cents": vest_income, "taxable_cents": taxable,
        "liability_cents": liability, "withheld_salary_cents": salary_wh, "withheld_supplemental_cents": supp_wh,
        "withheld_vests_cents": vests_wh, "withheld_cents": withheld, "balance_cents": balance,
        "marginal_pct": marginal, "threshold_cents": ALERT_THRESHOLD_CENTS,
        "alert": balance > ALERT_THRESHOLD_CENTS, "missing_price": any(v.value_cents is None for v in vests),
        "vests": vest_rows,
    }


def rsu_value(shares: int, price_cents: int | None, growth_pct: int, years_ahead: int) -> int | None:
    """Shares at today's price grown by growth_pct per year for years_ahead (>= 0) years, rounded half up."""
    if price_cents is None:
        return None
    n = max(0, years_ahead)
    return half_up_div(shares * price_cents * (100 + growth_pct) ** n, 100 ** n)
