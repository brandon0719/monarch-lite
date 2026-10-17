"""M2: budget settings, 50/30/20 meters, cash flow, spending breakdown."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import BudgetSettings
from ..services import budget as svc
from ..services import overview as ov

router = APIRouter(prefix="/api", tags=["budget"])

MAX_RANGE_DAYS = 3 * 366


class SettingsOut(BaseModel):
    take_home_cents: int | None
    needs_pct: int
    wants_pct: int
    savings_pct: int


class SettingsIn(BaseModel):
    take_home_cents: int = Field(gt=0)
    needs_pct: int = Field(ge=0, le=100)
    wants_pct: int = Field(ge=0, le=100)
    savings_pct: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _consistent(self):
        if self.needs_pct + self.wants_pct + self.savings_pct != 100:
            raise ValueError("Needs + Wants + Savings must add up to 100%")
        return self


def _settings_out(s: BudgetSettings) -> SettingsOut:
    return SettingsOut(take_home_cents=s.take_home_cents,
                       needs_pct=s.needs_pct, wants_pct=s.wants_pct, savings_pct=s.savings_pct)


@router.get("/budget/settings", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return _settings_out(svc.load_settings(db))


@router.put("/budget/settings", response_model=SettingsOut)
def put_settings(body: SettingsIn, db: Session = Depends(get_db)):
    row = db.get(BudgetSettings, svc.SETTINGS_ID) or BudgetSettings(id=svc.SETTINGS_ID)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    db.add(row)
    db.commit()
    return _settings_out(row)


class Targets(BaseModel):
    needs: int
    wants: int
    savings: int


class BudgetMonth(BaseModel):
    month: str
    is_current: bool
    needs_cents: int
    wants_cents: int
    savings_cents: int


class BudgetOut(BaseModel):
    configured: bool
    take_home_cents: int | None
    needs_pct: int
    wants_pct: int
    savings_pct: int
    base_cents: int | None
    targets: Targets | None
    months: list[BudgetMonth]


class CashflowMonth(BaseModel):
    month: str
    income_cents: int
    spent_cents: int
    saved_cents: int
    savings_rate: float | None


class CashflowOut(BaseModel):
    months: list[CashflowMonth]
    average_savings_rate: float | None


@router.get("/budget", response_model=BudgetOut)
def get_budget(months: int = Query(3, ge=1, le=24), db: Session = Depends(get_db)):
    s = svc.load_settings(db)
    configured = s.take_home_cents is not None
    base = s.take_home_cents if configured else None
    targets = (
        Targets(needs=base * s.needs_pct // 100, wants=base * s.wants_pct // 100, savings=base * s.savings_pct // 100)
        if configured else None
    )
    today = dt.date.today()
    current = today.strftime("%Y-%m")
    rows = []
    for month in svc.last_months(today, months):
        start, end = svc.month_range(month)
        spend = svc.bucket_spending(db, start, end)
        rows.append(BudgetMonth(
            month=month, is_current=month == current,
            needs_cents=spend["needs"], wants_cents=spend["wants"],
            savings_cents=svc.savings_moved(db, start, end),
        ))
    return BudgetOut(
        configured=configured, take_home_cents=s.take_home_cents,
        needs_pct=s.needs_pct, wants_pct=s.wants_pct, savings_pct=s.savings_pct,
        base_cents=base, targets=targets, months=rows,
    )


@router.get("/cashflow", response_model=CashflowOut)
def get_cashflow(months: int = Query(12, ge=1, le=36), db: Session = Depends(get_db)):
    rows, income_sum, saved_sum = [], 0, 0
    for month in svc.last_months(dt.date.today(), months):
        start, end = svc.month_range(month)
        income = svc.income_total(db, start, end)
        spent = svc.spent_total(db, start, end)
        saved = income - spent
        rate = round(saved / income, 4) if income > 0 else None
        if income > 0:
            income_sum, saved_sum = income_sum + income, saved_sum + saved
        rows.append(CashflowMonth(month=month, income_cents=income, spent_cents=spent, saved_cents=saved, savings_rate=rate))
    average = round(saved_sum / income_sum, 4) if income_sum > 0 else None
    return CashflowOut(months=rows, average_savings_rate=average)


class BreakdownCategory(BaseModel):
    category_id: int | None
    name: str
    bucket: str | None
    cents: int


class BreakdownMerchant(BaseModel):
    merchant: str
    cents: int
    count: int


class BreakdownOut(BaseModel):
    categories: list[BreakdownCategory]
    merchants: list[BreakdownMerchant]
    total_cents: int


@router.get("/breakdown", response_model=BreakdownOut)
def get_breakdown(start: dt.date, end: dt.date, db: Session = Depends(get_db)):
    if start > end or end == dt.date.max or (end - start).days > MAX_RANGE_DAYS:  # date.max: end + 1 day overflows
        raise HTTPException(422, "Pick a start on or before the end, at most 3 years apart")
    stop = end + dt.timedelta(days=1)  # `end` is inclusive, like the transactions filter
    return BreakdownOut(
        categories=ov.spending_by_category(db, start, stop),
        merchants=ov.top_merchants(db, start, stop),
        total_cents=ov.spending_total(db, start, stop),
    )
