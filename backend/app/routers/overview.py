"""GET /api/overview — numbers for the home page (UI refresh spec)."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager, joinedload, selectinload

from ..db import get_db
from ..models import Account, Transaction
from ..services import overview as svc
from .transactions import TxnOut, to_out

router = APIRouter(prefix="/api/overview", tags=["overview"])
RECENT = 8


class SpendingRow(BaseModel):
    category_id: int | None
    name: str
    cents: int


class OverviewOut(BaseModel):
    month: str
    net_worth_cents: int
    balances: dict[str, int]
    spent_cents: int
    spending_by_category: list[SpendingRow]
    to_review: int
    uncategorized: int
    last_synced_at: dt.datetime | None
    recent: list[TxnOut]


@router.get("", response_model=OverviewOut)
def get_overview(month: str | None = None, db: Session = Depends(get_db)):
    today = dt.date.today()
    month = month or today.strftime("%Y-%m")
    try:
        start, end = svc.month_range(month)
    except (ValueError, OverflowError):
        raise HTTPException(422, "month must be YYYY-MM") from None
    groups = svc.balances(db)
    spending = svc.spending_by_category(db, start, end)
    to_review, uncategorized = svc.review_counts(db, today)
    recent = db.scalars(
        select(Transaction)
        .join(Transaction.account)
        .where(Account.is_hidden.is_(False))
        .options(contains_eager(Transaction.account), joinedload(Transaction.category), selectinload(Transaction.tags))
        .order_by(Transaction.posted_date.desc(), Transaction.id.desc())
        .limit(RECENT)
    ).unique().all()
    return OverviewOut(
        month=month,
        net_worth_cents=sum(groups.values()),
        balances=groups,
        spent_cents=svc.spending_total(db, start, end),
        spending_by_category=spending,
        to_review=to_review,
        uncategorized=uncategorized,
        last_synced_at=svc.last_synced(db),
        recent=[to_out(t) for t in recent],
    )
