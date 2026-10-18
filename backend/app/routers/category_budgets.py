"""M2 round 2: per-category monthly budgets (FR-BUD-02)."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Category
from ..services import category_budgets as svc
from ..services.overview import SPENDING_BUCKETS, month_range
from .params import Id

router = APIRouter(prefix="/api/category-budgets", tags=["category-budgets"])
MAX_AMOUNT_CENTS = 100_000_000_00  # $100M
MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


class BudgetRow(BaseModel):
    category_id: int
    name: str
    bucket: str
    budget_cents: int
    spent_cents: int
    remaining_cents: int
    pct_used: float | None


class Unbudgeted(BaseModel):
    spent_cents: int
    categories: int


class CategoryBudgetsOut(BaseModel):
    month: str
    rows: list[BudgetRow]
    unbudgeted: Unbudgeted


class BudgetIn(BaseModel):
    month: str = Field(pattern=MONTH)
    amount_cents: int | None = Field(ge=0, le=MAX_AMOUNT_CENTS)


class BudgetSet(BudgetIn):
    category_id: int


@router.get("", response_model=CategoryBudgetsOut)
def get_category_budgets(month: str | None = Query(None, pattern=MONTH), db: Session = Depends(get_db)):
    month = month or dt.date.today().strftime("%Y-%m")
    start, end = month_range(month)
    budgets = svc.in_effect(db, month)
    spent = svc.net_by_category(db, start, end)
    rows, unbudgeted_cents, unbudgeted_count = [], 0, 0
    for c in db.scalars(select(Category).where(Category.bucket.in_(SPENDING_BUCKETS))):
        cents = spent.get(c.id, 0)
        if c.id in budgets:
            budget = budgets[c.id]
            rows.append(BudgetRow(
                category_id=c.id, name=c.name, bucket=c.bucket, budget_cents=budget, spent_cents=cents,
                remaining_cents=budget - cents, pct_used=round(cents / budget, 4) if budget else None,
            ))
        elif cents > 0:
            unbudgeted_cents, unbudgeted_count = unbudgeted_cents + cents, unbudgeted_count + 1
    rows.sort(key=lambda r: (r.pct_used is None, -(r.pct_used or 0), r.name))
    return CategoryBudgetsOut(month=month, rows=rows, unbudgeted=Unbudgeted(spent_cents=unbudgeted_cents, categories=unbudgeted_count))


@router.put("/{category_id}", response_model=BudgetSet)
def put_category_budget(category_id: Id, body: BudgetIn, db: Session = Depends(get_db)):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(404, "Category not found")
    if category.bucket not in SPENDING_BUCKETS:
        raise HTTPException(422, "Only Needs, Wants and Other categories can have a budget")
    svc.set_from(db, category_id, body.month, body.amount_cents)
    return BudgetSet(category_id=category_id, **body.model_dump())
