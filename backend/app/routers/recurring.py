"""M3 round 1: recurring bills and income (FR-REC-01..04)."""
import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, BalanceSnapshot, Category, RecurringDismissal, RecurringItem, Transaction
from ..services import paycheck
from ..services import recurring as svc
from . import income
from .params import MAX_ID, Id
from .category_budgets import MAX_AMOUNT_CENTS

router = APIRouter(prefix="/api/recurring", tags=["recurring"])
Cadence = Literal["weekly", "monthly", "yearly"]
REQUIRED = ("merchant", "name", "amount_cents", "cadence", "anchor_date", "follows_paycheck")
OUTLIER_FRACTION = 4  # a deposit more than 1/4 (25%) away from the modeled take-home is a bonus or sign-on month


def _nonzero(value: int | None) -> int | None:
    if value == 0:
        raise ValueError("Amount can't be zero")
    return value


class ItemIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    merchant: str = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1)
    amount_cents: int = Field(ge=-MAX_AMOUNT_CENTS, le=MAX_AMOUNT_CENTS)
    cadence: Cadence
    anchor_date: dt.date
    category_id: int | None = Field(default=None, ge=1, le=MAX_ID)
    follows_paycheck: bool = False
    _amount = field_validator("amount_cents")(_nonzero)


class ItemPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    merchant: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None, min_length=1)
    amount_cents: int | None = Field(default=None, ge=-MAX_AMOUNT_CENTS, le=MAX_AMOUNT_CENTS)
    cadence: Cadence | None = None
    anchor_date: dt.date | None = None
    category_id: int | None = Field(default=None, ge=1, le=MAX_ID)
    follows_paycheck: bool | None = None
    _amount = field_validator("amount_cents")(_nonzero)


class ItemOut(BaseModel):
    id: int
    merchant: str
    name: str
    amount_cents: int
    cadence: str
    anchor_date: dt.date
    category_id: int | None
    follows_paycheck: bool
    next_due: dt.date
    status: Literal["upcoming", "late"]
    last_amount_cents: int | None
    last_date: dt.date | None


class Suggestion(BaseModel):
    merchant: str
    cadence: str
    amount_cents: int
    count: int
    last_date: dt.date
    next_date: dt.date


class PriceAlert(BaseModel):
    kind: Literal["price_increase"] = "price_increase"
    item_id: int
    name: str
    previous_cents: int
    latest_cents: int
    date: dt.date


class NewAlert(BaseModel):
    kind: Literal["new_recurring"] = "new_recurring"
    merchant: str
    amount_cents: int
    cadence: str


class RecurringOut(BaseModel):
    items: list[ItemOut]
    suggestions: list[Suggestion]
    alerts: list[PriceAlert | NewAlert]


class MerchantIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    merchant: str = Field(min_length=1)


class UpcomingRow(BaseModel):
    date: dt.date
    item_id: int
    name: str
    amount_cents: int
    balance_cents: int | None
    late: bool


class UpcomingOut(BaseModel):
    start_balance_cents: int | None
    rows: list[UpcomingRow]
    bills_cents: int
    income_cents: int


def _paycheck_reference(db: Session) -> int | None:
    """Modeled monthly take-home from the salary profile in effect today; None without a profile or tax config."""
    today = dt.date.today()
    profiles = [income._as_profile(p) for p in income._profiles(db)]
    profile = paycheck.profile_on(profiles, today) or (profiles[-1] if profiles else None)
    if profile is None:
        return None
    try:
        ty, _ = income._tax_year_or_earlier(today.year)
    except HTTPException as exc:
        if exc.status_code != 404:  # a broken tax config should surface, not silently change the amount
            raise
        return None
    take_home = paycheck.monthly_take_home(profile, ty)
    return take_home if take_home > 0 else None  # withholding can exceed pay; that's no reference


def _expected(item: RecurringItem, history: list[tuple[dt.date, int]], reference: int | None) -> int:
    """The amount to expect: saved, or for a paycheck item the latest deposit near the modeled take-home."""
    if not item.follows_paycheck:
        return item.amount_cents
    deposits = [cents for _, cents in history]
    if reference is None:
        return deposits[-1] if deposits else item.amount_cents
    usual = [cents for cents in deposits if abs(cents - reference) * OUTLIER_FRACTION <= reference]
    return usual[-1] if usual else reference


def _scan(db: Session, item: RecurringItem, reference: int | None = None
          ) -> tuple[list[tuple[dt.date, int]], list[tuple[dt.date, int]], dt.date, int]:
    """(same-sign history, matching payments, next_due, expected amount) for an item; visible accounts, oldest first.

    `reference` is the modeled take-home (`_paycheck_reference`), used only by paycheck items."""
    rows = db.execute(
        select(Transaction.posted_date, Transaction.amount_cents)
        .join(Transaction.account)
        .where(Transaction.merchant == item.merchant, Account.is_hidden.is_(False))
        .order_by(Transaction.posted_date, Transaction.id)
    ).all()
    history = [(day, cents) for day, cents in rows if cents * item.amount_cents > 0]  # strictly same sign
    amount = _expected(item, history, reference)
    matches = [(day, cents) for day, cents in history if svc.amount_matches(amount, cents)]
    return history, matches, svc.next_due(item.anchor_date, item.cadence, [day for day, _ in matches]), amount


def _item_out(item: RecurringItem, matches: list[tuple[dt.date, int]], due: dt.date, today: dt.date,
              amount: int) -> ItemOut:
    last = matches[-1] if matches else (None, None)
    return ItemOut(
        id=item.id, merchant=item.merchant, name=item.name, amount_cents=amount, cadence=item.cadence,
        anchor_date=item.anchor_date, category_id=item.category_id, follows_paycheck=item.follows_paycheck, next_due=due,
        status="late" if svc.is_late(due, today) else "upcoming", last_date=last[0], last_amount_cents=last[1],
    )


def _suggestions(db: Session, today: dt.date) -> list[dict]:
    """Detected series that are still running: a series whose next charge is over 5 days overdue is cancelled."""
    rows = db.execute(
        select(Transaction.merchant, Transaction.posted_date, Transaction.amount_cents)
        .join(Transaction.account)
        .outerjoin(Category, Category.id == Transaction.category_id)
        .where(
            Account.is_hidden.is_(False),
            Transaction.merchant != "",
            Transaction.amount_cents != 0,
            or_(Category.id.is_(None), Category.bucket != "excluded"),
            Transaction.merchant.not_in(select(RecurringItem.merchant)),
            Transaction.merchant.not_in(select(RecurringDismissal.merchant)),
        )
    ).all()
    cutoff = today - dt.timedelta(days=svc.PAID_WINDOW_DAYS)
    return [s for s in svc.detect([tuple(r) for r in rows]) if s["next_date"] >= cutoff]


def _checking_balance(db: Session) -> int | None:
    """Latest snapshot per visible, open checking account, summed; None when there are none."""
    latest = (
        select(BalanceSnapshot.account_id, func.max(BalanceSnapshot.date).label("day"))
        .group_by(BalanceSnapshot.account_id)
        .subquery()
    )
    balances = db.scalars(
        select(BalanceSnapshot.balance_cents)
        .join(Account, Account.id == BalanceSnapshot.account_id)
        .join(latest, and_(latest.c.account_id == BalanceSnapshot.account_id, latest.c.day == BalanceSnapshot.date))
        .where(Account.type == "checking", Account.is_hidden.is_(False), Account.closed_at.is_(None))
    ).all()
    return sum(balances) if balances else None


def _check_category(db: Session, category_id: int | None) -> None:
    if category_id is not None and db.get(Category, category_id) is None:
        raise HTTPException(422, "Category not found")


def _single_out(db: Session, item: RecurringItem) -> ItemOut:
    _, matches, due, amount = _scan(db, item, _paycheck_reference(db) if item.follows_paycheck else None)
    return _item_out(item, matches, due, dt.date.today(), amount)


def _check_paycheck(follows: bool, amount_cents: int) -> None:
    if follows and amount_cents < 0:
        raise HTTPException(422, "Only income can follow your paycheck")


def _get_item(db: Session, item_id: int) -> RecurringItem:
    item = db.get(RecurringItem, item_id)
    if item is None:
        raise HTTPException(404, "Recurring item not found")
    return item


@router.get("", response_model=RecurringOut)
def get_recurring(db: Session = Depends(get_db)):
    today = dt.date.today()
    items, alerts = [], []
    all_items = list(db.scalars(select(RecurringItem)))
    reference = _paycheck_reference(db) if any(i.follows_paycheck for i in all_items) else None
    for item in all_items:
        history, matches, due, amount = _scan(db, item, reference)
        items.append(_item_out(item, matches, due, today, amount))
        if item.amount_cents >= 0:
            continue  # bills only
        # "Latest" is the newest charge that isn't a sibling item's (same merchant, matching its amount instead),
        # unfiltered by this item's 10% window so a rise past it still alerts. "Previous" is the newest earlier
        # charge that matches the item, so stray tiny charges never count.
        siblings = [o for o in all_items if o.id != item.id and o.merchant == item.merchant]
        own = [t for t in history if svc.amount_matches(item.amount_cents, t[1])
               or not any(svc.amount_matches(o.amount_cents, t[1]) for o in siblings)]
        prior = [t for t in own[:-1] if svc.amount_matches(item.amount_cents, t[1])]
        if prior and abs(own[-1][1]) > abs(prior[-1][1]):
            alerts.append(PriceAlert(item_id=item.id, name=item.name, previous_cents=prior[-1][1],
                                     latest_cents=own[-1][1], date=own[-1][0]))
    items.sort(key=lambda i: (i.next_due, i.name))
    suggestions = _suggestions(db, today)
    alerts += [NewAlert(merchant=s["merchant"], amount_cents=s["amount_cents"], cadence=s["cadence"]) for s in suggestions]
    return RecurringOut(items=items, suggestions=suggestions, alerts=alerts)


@router.post("/items", response_model=ItemOut, status_code=201)
def create_item(body: ItemIn, db: Session = Depends(get_db)):
    _check_category(db, body.category_id)
    _check_paycheck(body.follows_paycheck, body.amount_cents)
    item = RecurringItem(**body.model_dump(exclude={"name"}), name=body.name or body.merchant)
    db.add(item)
    db.commit()
    return _single_out(db, item)


@router.patch("/items/{item_id}", response_model=ItemOut)
def patch_item(item_id: Id, body: ItemPatch, db: Session = Depends(get_db)):
    item = _get_item(db, item_id)
    data = body.model_dump(exclude_unset=True)
    if any(key in data and data[key] is None for key in REQUIRED):
        raise HTTPException(422, "Merchant, name, amount, cadence, next date and paycheck setting can't be empty")
    _check_paycheck(data.get("follows_paycheck", item.follows_paycheck), data.get("amount_cents", item.amount_cents))
    if "category_id" in data:
        _check_category(db, data["category_id"])
    for key, value in data.items():
        setattr(item, key, value)
    db.commit()
    return _single_out(db, item)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: Id, db: Session = Depends(get_db)):
    db.delete(_get_item(db, item_id))
    db.commit()
    return Response(status_code=204)


@router.post("/suggestions/confirm", response_model=ItemOut, status_code=201)
def confirm_suggestion(body: MerchantIn, db: Session = Depends(get_db)):
    suggestion = next((s for s in _suggestions(db, dt.date.today()) if s["merchant"] == body.merchant), None)
    if suggestion is None:
        raise HTTPException(404, "No such suggestion")
    category_id = next(
        (
            cat
            for cents, cat in db.execute(
                select(Transaction.amount_cents, Transaction.category_id)
                .join(Transaction.account)
                .where(Transaction.merchant == body.merchant, Account.is_hidden.is_(False))
                .order_by(Transaction.posted_date.desc(), Transaction.id.desc())
            )
            if svc.amount_matches(suggestion["amount_cents"], cents)
        ),
        None,
    )
    item = RecurringItem(merchant=body.merchant, name=body.merchant, amount_cents=suggestion["amount_cents"],
                         cadence=suggestion["cadence"], anchor_date=suggestion["next_date"], category_id=category_id)
    db.add(item)
    db.commit()
    return _single_out(db, item)


@router.post("/suggestions/dismiss", status_code=204)
def dismiss_suggestion(body: MerchantIn, db: Session = Depends(get_db)):
    if db.get(RecurringDismissal, body.merchant) is None:
        db.add(RecurringDismissal(merchant=body.merchant))
        db.commit()
    return Response(status_code=204)


@router.get("/upcoming", response_model=UpcomingOut)
def get_upcoming(days: int = Query(30, ge=1, le=90), db: Session = Depends(get_db)):
    today = dt.date.today()
    horizon = today + dt.timedelta(days=days)
    planned = []
    all_items = list(db.scalars(select(RecurringItem)))
    reference = _paycheck_reference(db) if any(i.follows_paycheck for i in all_items) else None
    for item in all_items:
        _, _, due, amount = _scan(db, item, reference)
        late = svc.is_late(due, today)
        for day in svc.upcoming_dates(item.anchor_date, item.cadence, due, today, horizon):
            planned.append((day, item.name, item.id, amount, late and day == due))
    planned.sort(key=lambda p: (p[0], p[1]))
    start = _checking_balance(db)
    running, rows = start, []
    for day, name, item_id, cents, late in planned:
        running = None if running is None else running + cents
        rows.append(UpcomingRow(date=day, item_id=item_id, name=name, amount_cents=cents, balance_cents=running,
                                late=late))
    return UpcomingOut(
        start_balance_cents=start, rows=rows,
        bills_cents=sum(-p[3] for p in planned if p[3] < 0),
        income_cents=sum(p[3] for p in planned if p[3] > 0),
    )
