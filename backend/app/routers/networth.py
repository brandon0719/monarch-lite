"""M4: net worth over time (FR-NW-02)."""
import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, BalanceSnapshot, Transaction
from ..services import networth as svc

router = APIRouter(prefix="/api/networth", tags=["networth"])


class Point(BaseModel):
    date: dt.date
    assets_cents: int
    liabilities_cents: int
    net_cents: int
    estimated: bool


class NetWorthOut(BaseModel):
    points: list[Point]
    change_cents: int
    first_actual_date: dt.date | None


def _histories(db: Session) -> list[svc.AccountHistory]:
    out = []
    for acct in db.scalars(select(Account).where(Account.is_hidden.is_(False))):
        snaps = [tuple(r) for r in db.execute(
            select(BalanceSnapshot.date, BalanceSnapshot.balance_cents)
            .where(BalanceSnapshot.account_id == acct.id).order_by(BalanceSnapshot.date))]
        hist = svc.AccountHistory(type=acct.type, is_manual=acct.is_manual, closed_at=acct.closed_at, snapshots=snaps)
        if hist.rebuilds():
            hist.txns = [tuple(r) for r in db.execute(
                select(Transaction.posted_date, Transaction.amount_cents).where(Transaction.account_id == acct.id))]
        out.append(hist)
    return out


@router.get("", response_model=NetWorthOut)
def get_networth(range: Literal["1M", "3M", "YTD", "1Y", "ALL"] = "3M", db: Session = Depends(get_db)):
    hists = _histories(db)
    first = svc.earliest(hists)
    if first is None:
        return NetWorthOut(points=[], change_cents=0, first_actual_date=None)
    today = dt.date.today()
    # Sync dates snapshots in UTC, so a fresh one can be dated "tomorrow" locally; never leave one off the chart.
    end = max([today] + [h.snapshots[-1][0] for h in hists if h.snapshots])
    points = svc.series(hists, svc.range_start(range, today, first), end)
    # The first day with no estimated account: the latest of the accounts' first snapshots.
    actual = [h.snapshots[0][0] for h in hists if h.snapshots]
    return NetWorthOut(points=points, change_cents=points[-1]["net_cents"] - points[0]["net_cents"] if points else 0,
                       first_actual_date=max(actual) if actual else None)
