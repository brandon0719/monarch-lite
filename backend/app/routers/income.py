"""M5 round 2: salary profiles, sign-on payments, modeled paychecks and clawback (FR-INC-01, 02, 03, 05, 06)."""
import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, CashPayment, Category, IncomeProfile, RsuGrant, RsuVest, Transaction
from ..services import estimate, paycheck, prices, tax
from .params import MAX_DAY, MIN_DAY, Day, Id

router = APIRouter(prefix="/api/income", tags=["income"])

MAX_CENTS = 1_000_000_000  # $10M
MAX_SPAN_YEARS = 10
YearQuery = Annotated[int, Query(ge=MIN_DAY.year, le=MAX_DAY.year)]
PAYCHECK_CATEGORY = "Paycheck"


class ProfileIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    effective_from: Day
    salary_cents: int = Field(ge=1, le=MAX_CENTS)
    pay_frequency: Literal["monthly"] = "monthly"
    k401_pct: int = Field(ge=0, le=100)
    filing_status: Literal["single", "married_jointly"]
    extra_withholding_cents: int = Field(0, ge=0, le=100_000_000)  # $1M
    employment_start: Day


class ProfileOut(BaseModel):
    id: int
    effective_from: dt.date
    salary_cents: int
    pay_frequency: str
    k401_pct: int
    filing_status: str
    extra_withholding_cents: int
    employment_start: dt.date


def _plus_years(day: dt.date, years: int) -> dt.date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # Feb 29
        return day.replace(year=day.year + years, day=28)


def _window(start: dt.date, end: dt.date, what: str) -> None:
    if start >= end:
        raise ValueError(f"{what} start must be before its end")
    if end > _plus_years(start, MAX_SPAN_YEARS):
        raise ValueError(f"{what} can span at most {MAX_SPAN_YEARS} years")


class PaymentIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=100)
    kind: Literal["lump", "installments"]
    amount_cents: int = Field(ge=1, le=MAX_CENTS)
    paid_date: Day | None = None
    start_date: Day | None = None
    end_date: Day | None = None
    repay_start: Day | None = None
    repay_end: Day | None = None

    @model_validator(mode="after")
    def _rules(self):
        if self.kind == "lump":
            if self.paid_date is None:
                raise ValueError("A lump payment needs a paid date")
            if self.start_date or self.end_date:
                raise ValueError("A lump payment can't have installment dates")
        else:
            if self.start_date is None or self.end_date is None:
                raise ValueError("Installments need a start and an end date")
            if self.paid_date:
                raise ValueError("Installments can't have a paid date")
            _window(self.start_date, self.end_date, "The installment window")
            if paycheck.month_end(self.start_date) >= self.end_date:
                raise ValueError("The installment window must include at least one payday (a month-end)")
        if (self.repay_start is None) != (self.repay_end is None):
            raise ValueError("The repay window needs both a start and an end")
        if self.repay_start and self.repay_end:
            _window(self.repay_start, self.repay_end, "The repay window")
        return self


class PaymentPatch(BaseModel):
    """Loose on purpose: the merged row is re-validated by PaymentIn, so every rule lives in one place."""

    model_config = ConfigDict(str_strip_whitespace=True)
    label: str | None = None
    kind: str | None = None
    amount_cents: int | None = None
    paid_date: dt.date | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    repay_start: dt.date | None = None
    repay_end: dt.date | None = None


class PaymentOut(BaseModel):
    id: int
    label: str
    kind: str
    amount_cents: int
    paid_date: dt.date | None
    start_date: dt.date | None
    end_date: dt.date | None
    repay_start: dt.date | None
    repay_end: dt.date | None


class LineOut(BaseModel):
    name: str
    cents: int


class PaycheckOut(BaseModel):
    date: dt.date
    kind: Literal["regular", "payment"]
    label: str
    gross_cents: int
    lines: list[LineOut]
    net_cents: int


class MonthOut(BaseModel):
    month: str
    modeled_net_cents: int
    actual_cents: int


class PaychecksOut(BaseModel):
    year: int
    paychecks: list[PaycheckOut]
    months: list[MonthOut]
    monthly_take_home_cents: int | None
    tax_year_used: int
    tax_year_fallback: bool


class ClawbackItem(BaseModel):
    payment_id: int
    label: str
    owed_today_cents: int
    zero_date: dt.date


class ClawbackOut(BaseModel):
    items: list[ClawbackItem]
    total_cents: int


def _tax_year(year: int) -> tax.TaxYear:
    try:
        ty = tax.load_year(year)
    except ValueError as exc:  # a server config error, not bad input: the one acceptable 500
        raise HTTPException(500, f"Tax config for {year} is invalid: {exc}") from None
    if ty is None:
        raise HTTPException(404, f"No tax config for {year}")
    return ty


def _tax_year_or_earlier(year: int) -> tuple[tax.TaxYear, int]:
    """The year's tax config, else the most recent earlier one (404 only when there is none)."""
    try:
        for candidate in (year, *tax.years_before(year)):
            if (ty := tax.load_year(candidate)) is not None:
                return ty, candidate
    except ValueError as exc:
        raise HTTPException(500, f"Tax config for {candidate} is invalid: {exc}") from None
    raise HTTPException(404, f"No tax config for {year}")


def _payment(db: Session, payment_id: int) -> CashPayment:
    row = db.get(CashPayment, payment_id)
    if row is None:
        raise HTTPException(404, "Payment not found")
    return row


def _validated(data: dict) -> PaymentIn:
    try:
        return PaymentIn(**data)
    except ValidationError as exc:
        err = exc.errors()[0]
        field = ".".join(str(p) for p in err["loc"])
        raise HTTPException(422, f"{field + ': ' if field else ''}{err['msg'].removeprefix('Value error, ')}") from None


def _payments(db: Session) -> list[paycheck.Payment]:
    return [paycheck.Payment(p.id, p.label, p.kind, p.amount_cents, p.paid_date, p.start_date, p.end_date, p.repay_start, p.repay_end)
            for p in db.scalars(select(CashPayment).order_by(CashPayment.id))]


def _profiles(db: Session) -> list[IncomeProfile]:
    return list(db.scalars(select(IncomeProfile).order_by(IncomeProfile.effective_from)))


def _as_profile(p: IncomeProfile) -> paycheck.Profile:
    return paycheck.Profile(p.effective_from, p.salary_cents, p.k401_pct, p.filing_status, p.extra_withholding_cents, p.employment_start)


@router.get("/profiles", response_model=list[ProfileOut])
def list_profiles(db: Session = Depends(get_db)):
    return list(reversed(_profiles(db)))


@router.put("/profiles", response_model=ProfileOut)
def put_profile(body: ProfileIn, db: Session = Depends(get_db)):
    def upsert() -> IncomeProfile:
        row = db.scalar(select(IncomeProfile).where(IncomeProfile.effective_from == body.effective_from))
        if row is None:
            row = IncomeProfile()
            db.add(row)
        for key, value in body.model_dump().items():
            setattr(row, key, value)
        db.commit()
        return row

    try:
        return upsert()
    except IntegrityError:  # a concurrent request inserted the same day first: re-select and update that row
        db.rollback()
        return upsert()


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: Id, db: Session = Depends(get_db)):
    row = db.get(IncomeProfile, profile_id)
    if row is None:
        raise HTTPException(404, "Profile not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.get("/tax-config")
def tax_config(year: YearQuery):
    return _tax_year(year).raw


@router.get("/payments", response_model=list[PaymentOut])
def list_payments(db: Session = Depends(get_db)):
    return list(db.scalars(select(CashPayment).order_by(CashPayment.id)))


@router.post("/payments", response_model=PaymentOut, status_code=201)
def create_payment(body: PaymentIn, db: Session = Depends(get_db)):
    row = CashPayment(**body.model_dump())
    db.add(row)
    db.commit()
    return row


@router.patch("/payments/{payment_id}", response_model=PaymentOut)
def patch_payment(payment_id: Id, body: PaymentPatch, db: Session = Depends(get_db)):
    row = _payment(db, payment_id)
    patch = body.model_dump(exclude_unset=True)
    if any(key in patch and patch[key] is None for key in ("label", "kind", "amount_cents")):
        raise HTTPException(422, "Label, kind and amount can't be empty")
    merged = {key: getattr(row, key) for key in PaymentIn.model_fields} | patch
    for key, value in _validated(merged).model_dump().items():
        setattr(row, key, value)
    db.commit()
    return row


@router.delete("/payments/{payment_id}", status_code=204)
def delete_payment(payment_id: Id, db: Session = Depends(get_db)):
    db.delete(_payment(db, payment_id))
    db.commit()
    return Response(status_code=204)


@router.get("/clawback", response_model=ClawbackOut)
def clawback(db: Session = Depends(get_db)):
    today = dt.date.today()
    items = []
    for pay in _payments(db):
        owed = paycheck.clawback_owed(pay, today)
        if owed is not None:
            items.append(ClawbackItem(payment_id=pay.id, label=pay.label, owed_today_cents=owed, zero_date=pay.repay_end))
    return ClawbackOut(items=items, total_cents=sum(i.owed_today_cents for i in items))


def _actual_by_month(db: Session, year: int) -> dict[str, int]:
    month = func.strftime("%Y-%m", Transaction.posted_date)
    rows = db.execute(
        select(month, func.sum(Transaction.amount_cents))
        .join(Account, Account.id == Transaction.account_id)
        .join(Category, Category.id == Transaction.category_id)
        .where(Category.name == PAYCHECK_CATEGORY, Account.is_hidden.is_(False), Transaction.amount_cents > 0,
               Transaction.posted_date >= dt.date(year, 1, 1), Transaction.posted_date <= dt.date(year, 12, 31))
        .group_by(month)
    )
    return {m: total for m, total in rows}


@router.get("/paychecks", response_model=PaychecksOut)
def paychecks(year: YearQuery = None, db: Session = Depends(get_db)):
    year = year or dt.date.today().year
    profiles = _profiles(db)
    if not profiles:
        return PaychecksOut(year=year, paychecks=[], months=[], monthly_take_home_cents=None,
                            tax_year_used=year, tax_year_fallback=False)
    ty, used = _tax_year_or_earlier(year)
    rows = paycheck.build_year([_as_profile(p) for p in profiles], _payments(db), ty, year)
    modeled: dict[str, int] = {}
    for row in rows:
        key = row["date"].strftime("%Y-%m")
        modeled[key] = modeled.get(key, 0) + row["net_cents"]
    actual = _actual_by_month(db, year)
    months = [MonthOut(month=m, modeled_net_cents=modeled.get(m, 0), actual_cents=actual.get(m, 0)) for m in sorted(modeled | actual)]
    return PaychecksOut(year=year, paychecks=rows, months=months,
                        monthly_take_home_cents=paycheck.monthly_take_home(_as_profile(profiles[-1]), ty),
                        tax_year_used=used, tax_year_fallback=used != year)


class EstimateVestOut(BaseModel):
    vest_date: dt.date
    grant_label: str
    shares: int
    value_cents: int | None
    withheld_cents: int | None
    shortfall_cents: int | None


class TaxEstimateOut(BaseModel):
    year: int
    tax_year_used: int
    tax_year_fallback: bool
    has_profile: bool
    filing_status: str
    wages_cents: int
    pretax_cents: int
    vest_income_cents: int
    taxable_cents: int
    liability_cents: int
    withheld_salary_cents: int
    withheld_supplemental_cents: int
    withheld_vests_cents: int
    withheld_cents: int
    balance_cents: int
    marginal_pct: int
    threshold_cents: int
    alert: bool
    missing_price: bool
    vests: list[EstimateVestOut]


class CompPrice(BaseModel):
    symbol: str
    price_cents: int


class CompYear(BaseModel):
    year: int
    salary_cents: int
    cash_cents: int
    rsu_shares: int
    rsu_cents: int | None
    total_cents: int | None


class CompOut(BaseModel):
    growth_pct: int
    price: CompPrice | None
    years: list[CompYear]


def _price_cents(db: Session, symbol: str, cache: dict) -> int | None:
    if symbol not in cache:
        got = prices.get_price(db, symbol)
        cache[symbol] = got[0] if got else None
    return cache[symbol]


def _vest_events(db: Session, year: int, cache: dict) -> list[estimate.VestEvent]:
    rows = db.execute(
        select(RsuVest.vest_date, RsuVest.shares, RsuGrant.label, RsuGrant.symbol)
        .join(RsuGrant, RsuGrant.id == RsuVest.grant_id)
        .where(RsuVest.vest_date >= dt.date(year, 1, 1), RsuVest.vest_date <= dt.date(year, 12, 31))
        .order_by(RsuVest.vest_date, RsuVest.id)
    ).all()
    out = []
    for day, shares, label, symbol in rows:
        price = _price_cents(db, symbol, cache)
        out.append(estimate.VestEvent(day, label, shares, None if price is None else shares * price))
    return out


@router.get("/tax-estimate", response_model=TaxEstimateOut)
def tax_estimate(year: YearQuery = None, db: Session = Depends(get_db)):
    year = year or dt.date.today().year
    ty, used = _tax_year_or_earlier(year)
    profiles = [_as_profile(p) for p in _profiles(db)]
    rows = paycheck.build_year(profiles, _payments(db), ty, year) if profiles else []
    # Every profile may start after the year's end; build_year then uses the earliest one, so do the same here.
    current = (paycheck.profile_on(profiles, dt.date(year, 12, 31)) or profiles[0]) if profiles else None
    filing = current.filing_status if current else "single"
    result = estimate.year_estimate(rows, _vest_events(db, year, {}), filing, ty)
    if not profiles:  # no salary model: vests are listed, but there is no estimate to headline or alert on
        result |= {k: 0 for k in result if k.endswith("_cents") and k != "threshold_cents"} | {"marginal_pct": 0, "alert": False}
        for v in result["vests"]:  # the marginal rate is meaningless without a salary model
            v["shortfall_cents"] = None
    return TaxEstimateOut(year=year, tax_year_used=used, tax_year_fallback=used != year,
                          has_profile=bool(profiles), filing_status=filing, **result)


@router.get("/comp-projection", response_model=CompOut)
def comp_projection(growth_pct: Annotated[int, Query(ge=-50, le=100)] = 0, db: Session = Depends(get_db)):
    today = dt.date.today()
    profiles = [_as_profile(p) for p in _profiles(db)]
    payments = _payments(db)
    vests = db.execute(select(RsuVest.vest_date, RsuVest.shares)).all()
    if not profiles and not vests:
        return CompOut(growth_pct=growth_pct, price=None, years=[])
    symbols = list(db.scalars(select(RsuGrant.symbol).order_by(RsuGrant.grant_date, RsuGrant.id)))
    symbol = "AMZN" if "AMZN" in symbols else (symbols[0] if symbols else None)
    price = _price_cents(db, symbol, {}) if symbol else None
    # Spec: earliest of (employment start, first vest) .. latest of (last vest, last payment, this year); clamped to the
    # validated 2000..2100 window so a stray out-of-range row can't turn this into thousands of build_year calls.
    starts = [d.year for d, _ in vests] + ([min(p.employment_start for p in profiles).year] if profiles else [])
    ends = [d.year for d, _ in vests] + [today.year]
    for p in payments:
        ends.append((p.paid_date or p.end_date - dt.timedelta(days=1)).year)  # an installment window's end is exclusive
    first, last = max(min(starts), MIN_DAY.year), min(max(ends), MAX_DAY.year)
    ty, _ = _tax_year_or_earlier(today.year)  # gross pay doesn't depend on the tax table
    out = []
    for year in range(first, last + 1):
        rows = paycheck.build_year(profiles, payments, ty, year) if profiles else []
        salary = sum(r["gross_cents"] for r in rows if r["kind"] == "regular")
        cash = sum(r["gross_cents"] for r in rows if r["kind"] == "payment")
        shares = sum(s for d, s in vests if d.year == year)
        rsu = 0 if shares == 0 else estimate.rsu_value(shares, price, growth_pct, year - today.year)
        out.append(CompYear(year=year, salary_cents=salary, cash_cents=cash, rsu_shares=shares, rsu_cents=rsu,
                            total_cents=None if rsu is None else salary + cash + rsu))
    return CompOut(growth_pct=growth_pct, price=CompPrice(symbol=symbol, price_cents=price) if symbol and price is not None else None,
                   years=out)
