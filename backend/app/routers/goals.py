"""M3 round 2: savings goals (FR-GOAL-01, FR-GOAL-02)."""
import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, BalanceSnapshot, Goal, GoalAccount, GoalContribution
from ..services import goals as svc
from .params import MAX_ID, Id
from .category_budgets import MAX_AMOUNT_CENTS

router = APIRouter(prefix="/api/goals", tags=["goals"])
AccountId = Annotated[int, Field(ge=1, le=MAX_ID)]


class GoalIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    target_cents: int = Field(gt=0, le=MAX_AMOUNT_CENTS)
    target_date: dt.date | None = None
    kind: Literal["linked", "manual"]
    account_ids: list[AccountId] = []


class GoalPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    target_cents: int | None = Field(default=None, gt=0, le=MAX_AMOUNT_CENTS)
    target_date: dt.date | None = None
    account_ids: list[AccountId] | None = None


class ContributionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    date: dt.date
    amount_cents: int = Field(ge=-MAX_AMOUNT_CENTS, le=MAX_AMOUNT_CENTS)
    note: str | None = Field(default=None, max_length=200)

    @field_validator("amount_cents")
    @classmethod
    def _nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Amount can't be zero")
        return value

    @field_validator("date")
    @classmethod
    def _not_future(cls, value: dt.date) -> dt.date:
        if value > dt.date.today():
            raise ValueError("The contribution date can't be in the future")
        return value


class AccountRef(BaseModel):
    id: int
    name: str


class ContributionOut(BaseModel):
    id: int
    date: dt.date
    amount_cents: int
    note: str | None


class GoalOut(BaseModel):
    id: int
    name: str
    kind: str
    target_cents: int
    target_date: dt.date | None
    current_cents: int
    pct: float
    rate_cents: int | None
    history_days: int | None
    needed_cents: int | None
    status: Literal["done", "no_date", "unknown", "on_track", "behind"]
    reach_by: dt.date | None
    accounts: list[AccountRef]
    contributions: list[ContributionOut]


def _balances(db: Session, account_ids: list[int], today: dt.date) -> tuple[int, int, int | None]:
    """(current, base, history_days): base is each account's latest snapshot on or before today-90, else its earliest."""
    cutoff = today - dt.timedelta(days=svc.RATE_WINDOW_DAYS)
    current = base = 0
    oldest: dt.date | None = None
    for account_id in account_ids:
        snaps = db.execute(
            select(BalanceSnapshot.date, BalanceSnapshot.balance_cents)
            .where(BalanceSnapshot.account_id == account_id)
            .order_by(BalanceSnapshot.date)
        ).all()
        if not snaps:
            continue
        current += snaps[-1][1]
        before = [s for s in snaps if s[0] <= cutoff]
        day, cents = before[-1] if before else snaps[0]
        base += cents
        oldest = day if oldest is None or day < oldest else oldest
    return current, base, None if oldest is None else (today - oldest).days


def _goal_out(db: Session, goal: Goal, today: dt.date) -> GoalOut:
    if goal.kind == "linked":
        current, base, days = _balances(db, [link.account_id for link in goal.links], today)
        rate = None if days is None else svc.monthly_rate(current - base, days)
    else:
        current = sum(c.amount_cents for c in goal.contributions)
        start = min([c.date for c in goal.contributions] + [goal.created_at.date()])
        days = max(min(svc.RATE_WINDOW_DAYS, (today - start).days), 0)
        since = today - dt.timedelta(days=svc.RATE_WINDOW_DAYS)
        rate = svc.monthly_rate(sum(c.amount_cents for c in goal.contributions if since <= c.date <= today), days)
    remaining = goal.target_cents - current
    needed = svc.needed_per_month(remaining, today, goal.target_date) if goal.target_date else None
    return GoalOut(
        id=goal.id, name=goal.name, kind=goal.kind, target_cents=goal.target_cents, target_date=goal.target_date,
        current_cents=current, pct=round(current / goal.target_cents, 4), rate_cents=rate, history_days=days,
        needed_cents=needed,
        status=svc.status(current, goal.target_cents, rate, needed or 0, goal.target_date is not None),
        reach_by=None if goal.target_date else svc.reach_by(today, remaining, rate),
        accounts=[AccountRef(id=link.account.id, name=link.account.name) for link in goal.links],
        contributions=[ContributionOut(id=c.id, date=c.date, amount_cents=c.amount_cents, note=c.note) for c in goal.contributions],
    )


def _get(db: Session, goal_id: int) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    return goal


def _set_accounts(db: Session, goal: Goal, account_ids: list[int]) -> None:
    ids = list(dict.fromkeys(account_ids))
    for account_id in ids:
        if db.get(Account, account_id) is None:
            raise HTTPException(422, "Account not found")
    other = select(GoalAccount.account_id).where(GoalAccount.account_id.in_(ids))
    if goal.id is not None:
        other = other.where(GoalAccount.goal_id != goal.id)
    if db.scalar(other.limit(1)) is not None:
        raise HTTPException(409, "That account is already linked to another goal")
    # Keep existing links so re-saving one never deletes and re-inserts the same primary key.
    keep = [link for link in goal.links if link.account_id in ids]
    have = {link.account_id for link in keep}
    goal.links = keep + [GoalAccount(account_id=account_id) for account_id in ids if account_id not in have]


def _commit_or_409(db: Session) -> None:
    """A concurrent request can link the same account between the check and the insert; the PK catches it."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That account is already linked to another goal") from None


@router.get("", response_model=list[GoalOut])
def list_goals(db: Session = Depends(get_db)):
    today = dt.date.today()
    return [_goal_out(db, goal, today) for goal in db.scalars(select(Goal).order_by(Goal.created_at, Goal.id))]


@router.post("", response_model=GoalOut, status_code=201)
def create_goal(body: GoalIn, db: Session = Depends(get_db)):
    if body.kind == "manual" and body.account_ids:
        raise HTTPException(422, "Manual goals can't link accounts")
    goal = Goal(name=body.name, target_cents=body.target_cents, target_date=body.target_date, kind=body.kind)
    _set_accounts(db, goal, body.account_ids)
    db.add(goal)
    _commit_or_409(db)
    return _goal_out(db, goal, dt.date.today())


@router.patch("/{goal_id}", response_model=GoalOut)
def patch_goal(goal_id: Id, body: GoalPatch, db: Session = Depends(get_db)):
    goal = _get(db, goal_id)
    data = body.model_dump(exclude_unset=True)
    if any(key in data and data[key] is None for key in ("name", "target_cents", "account_ids")):
        raise HTTPException(422, "Name, target and accounts can't be empty")
    if "account_ids" in data:
        ids = data.pop("account_ids")
        if goal.kind == "manual" and ids:
            raise HTTPException(422, "Manual goals can't link accounts")
        _set_accounts(db, goal, ids)
    for key, value in data.items():
        setattr(goal, key, value)
    _commit_or_409(db)
    return _goal_out(db, goal, dt.date.today())


@router.delete("/{goal_id}", status_code=204)
def delete_goal(goal_id: Id, db: Session = Depends(get_db)):
    db.delete(_get(db, goal_id))
    db.commit()
    return Response(status_code=204)


@router.post("/{goal_id}/contributions", response_model=GoalOut, status_code=201)
def add_contribution(goal_id: Id, body: ContributionIn, db: Session = Depends(get_db)):
    goal = _get(db, goal_id)
    if goal.kind != "manual":
        raise HTTPException(422, "Only manual goals take contributions")
    db.add(GoalContribution(goal_id=goal.id, date=body.date, amount_cents=body.amount_cents, note=body.note or None))
    db.commit()
    db.refresh(goal)
    return _goal_out(db, goal, dt.date.today())


@router.delete("/{goal_id}/contributions/{contribution_id}", status_code=204)
def delete_contribution(goal_id: Id, contribution_id: Id, db: Session = Depends(get_db)):
    contribution = db.get(GoalContribution, contribution_id)
    if contribution is None or contribution.goal_id != goal_id:
        raise HTTPException(404, "Contribution not found")
    db.delete(contribution)
    db.commit()
    return Response(status_code=204)
