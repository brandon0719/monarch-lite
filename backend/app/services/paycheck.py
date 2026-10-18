"""Modeled paychecks, sign-on payments and clawback (M5 R2 spec). Pure functions; integer cents; monthly pay."""
import calendar
import datetime as dt
from dataclasses import dataclass

from . import tax
from .tax import TaxYear, half_up_div

PERIODS = 12


@dataclass(frozen=True)
class Profile:
    effective_from: dt.date
    salary_cents: int
    k401_pct: int
    filing_status: str
    extra_withholding_cents: int
    employment_start: dt.date


@dataclass(frozen=True)
class Payment:
    id: int
    label: str
    kind: str  # lump | installments
    amount_cents: int
    paid_date: dt.date | None
    start_date: dt.date | None
    end_date: dt.date | None
    repay_start: dt.date | None
    repay_end: dt.date | None


def month_end(day: dt.date) -> dt.date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def paydays(start: dt.date, until: dt.date) -> list[dt.date]:
    """Last day of each month from `start`'s month while it is on or before `until`."""
    out, day = [], month_end(start)
    while day <= until:
        out.append(day)
        day = month_end(day + dt.timedelta(days=1))
    return out


def profile_on(profiles: list[Profile], day: dt.date) -> Profile | None:
    eligible = [p for p in profiles if p.effective_from <= day]
    return max(eligible, key=lambda p: p.effective_from) if eligible else None


def regular_gross(profile: Profile, payday: dt.date, first_start: dt.date) -> int:
    monthly = half_up_div(profile.salary_cents, PERIODS)
    if (payday.year, payday.month) != (first_start.year, first_start.month):
        return monthly
    days_in = calendar.monthrange(payday.year, payday.month)[1]
    return half_up_div(monthly * (days_in - first_start.day + 1), days_in)


def installment_amounts(payment: Payment, days: list[dt.date]) -> list[tuple[dt.date, int]]:
    if payment.start_date is None or payment.end_date is None:
        return []  # a malformed row pays nothing rather than failing the whole schedule
    window = [d for d in days if payment.start_date <= d < payment.end_date]
    if not window:
        return []
    each = payment.amount_cents // len(window)
    amounts = [each] * len(window)
    amounts[-1] += payment.amount_cents - each * len(window)
    return list(zip(window, amounts))


def _payroll_lines(gross: int, ty: TaxYear, ytd_before: int) -> list[dict]:
    lines = [{"name": "Social Security", "cents": tax.social_security(gross, ytd_before, ty)},
             {"name": "Medicare", "cents": tax.medicare(gross, ytd_before, ty)}]
    return lines + [{"name": name, "cents": tax.pct_of(gross, bp)} for name, bp in ty.state_payroll if bp > 0]


def regular_paycheck(gross: int, profile: Profile, ty: TaxYear, ytd_before: int) -> tuple[list[dict], int]:
    k401 = half_up_div(gross * profile.k401_pct, 100)
    federal = tax.federal_regular(gross - k401, PERIODS, profile.filing_status, ty, profile.extra_withholding_cents)
    lines = [{"name": "401(k)", "cents": k401}, {"name": "Federal withholding", "cents": federal}]
    lines += _payroll_lines(gross, ty, ytd_before)  # 401(k) does not reduce FICA or state payroll wages
    lines = [l for l in lines if l["cents"] or l["name"] != "401(k)"]  # hide a 0% 401(k); keep $0 tax lines
    return lines, gross - sum(l["cents"] for l in lines)


def payment_paycheck(gross: int, ty: TaxYear, ytd_before: int, ytd_supp_before: int) -> tuple[list[dict], int]:
    lines = [{"name": "Federal withholding (supplemental)", "cents": tax.federal_supplemental(gross, ytd_supp_before, ty)}]
    lines += _payroll_lines(gross, ty, ytd_before)
    return lines, gross - sum(l["cents"] for l in lines)


def build_year(profiles: list[Profile], payments: list[Payment], ty: TaxYear, year: int) -> list[dict]:
    if not profiles:
        return []
    first_start = min(p.employment_start for p in profiles)
    # Installments split across every payday in their window, so generate through the latest end date.
    horizon = max([dt.date(max(year, first_start.year), 12, 31)] + [p.end_date for p in payments if p.end_date])
    days = paydays(first_start, horizon)
    earliest = min(profiles, key=lambda p: p.effective_from)  # paydays before any profile takes effect still use the earliest one
    events = []
    for day in days:
        if day.year == year:
            p = profile_on(profiles, day) or earliest
            events.append((day, 0, "Salary", regular_gross(p, day, first_start), p))
    for pay in payments:
        if pay.kind == "lump" and pay.paid_date and pay.paid_date.year == year:
            events.append((pay.paid_date, 1, pay.label, pay.amount_cents, None))
        elif pay.kind == "installments":
            events += [(d, 1, pay.label, c, None) for d, c in installment_amounts(pay, days) if d.year == year]
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    rows, ytd, ytd_supp = [], 0, 0
    for day, order, label, gross, prof in events:
        if order == 0:
            lines, net = regular_paycheck(gross, prof, ty, ytd)
        else:
            lines, net = payment_paycheck(gross, ty, ytd, ytd_supp)
            ytd_supp += gross
        ytd += gross
        rows.append({"date": day, "kind": "regular" if order == 0 else "payment", "label": label,
                     "gross_cents": gross, "lines": lines, "net_cents": net})
    return rows


def monthly_take_home(profile: Profile, ty: TaxYear) -> int:
    return regular_paycheck(half_up_div(profile.salary_cents, PERIODS), profile, ty, 0)[1]


def clawback_owed(payment: Payment, today: dt.date) -> int | None:
    """Unearned, daily-prorated amount owed if employment ended today; None without a repay window."""
    if payment.repay_start is None or payment.repay_end is None:
        return None
    total_days = (payment.repay_end - payment.repay_start).days
    if total_days <= 0:
        return None
    left = max(0, (payment.repay_end - max(today, payment.repay_start)).days)
    return half_up_div(payment.amount_cents * left, total_days)
