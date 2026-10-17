"""FR-ACC-04 status, FR-ACC-07 hide/close, FR-ACC-06 manual accounts."""
import datetime as dt
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, BalanceSnapshot
from .category_budgets import MAX_AMOUNT_CENTS
from .params import Id

router = APIRouter(prefix="/api/accounts", tags=["accounts"])
AccountType = Literal["checking", "savings", "credit", "investment", "loan", "other"]


class AccountOut(BaseModel):
    id: int
    institution: str
    name: str
    type: str
    is_hidden: bool
    is_manual: bool
    closed_at: dt.date | None
    last_synced_at: dt.datetime | None
    last_error: str | None
    balance_cents: int | None
    balance_date: dt.date | None


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: AccountType | None = None
    is_hidden: bool | None = None
    closed_at: dt.date | None = None

    @model_validator(mode="after")
    def _no_nulls(self):
        # Runs before the handler, so a rejected PATCH never touches the session.
        for key in self.model_fields_set:
            if key != "closed_at" and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


def _latest_snapshots(db: Session) -> dict[int, BalanceSnapshot]:
    latest = (
        select(BalanceSnapshot.account_id, func.max(BalanceSnapshot.date).label("date"))
        .group_by(BalanceSnapshot.account_id)
        .subquery()
    )
    rows = db.scalars(
        select(BalanceSnapshot).join(
            latest, and_(BalanceSnapshot.account_id == latest.c.account_id, BalanceSnapshot.date == latest.c.date)
        )
    )
    return {snap.account_id: snap for snap in rows}


def _out(account: Account, snap: BalanceSnapshot | None) -> AccountOut:
    return AccountOut(
        id=account.id,
        institution=account.institution,
        name=account.name,
        type=account.type,
        is_hidden=account.is_hidden,
        is_manual=account.is_manual,
        closed_at=account.closed_at,
        last_synced_at=account.last_synced_at,
        last_error=account.last_error,
        balance_cents=snap.balance_cents if snap else None,
        balance_date=snap.date if snap else None,
    )


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    snaps = _latest_snapshots(db)
    return [_out(a, snaps.get(a.id)) for a in db.scalars(select(Account).order_by(Account.type, Account.name))]


@router.patch("/{account_id}", response_model=AccountOut)
def patch_account(account_id: Id, body: AccountPatch, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(account, key, value)
    db.commit()
    return _out(account, _latest_snapshots(db).get(account.id))


def _not_future(value: dt.date | None) -> dt.date | None:
    if value is not None and value > dt.date.today():
        raise ValueError("The balance date can't be in the future")
    return value


class ManualAccountIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    institution: str = Field(default="Manual", min_length=1, max_length=100)
    type: AccountType
    balance_cents: int = Field(ge=-MAX_AMOUNT_CENTS, le=MAX_AMOUNT_CENTS)
    as_of: dt.date | None = None

    _as_of_not_future = field_validator("as_of")(_not_future)


class BalanceIn(BaseModel):
    balance_cents: int = Field(ge=-MAX_AMOUNT_CENTS, le=MAX_AMOUNT_CENTS)
    as_of: dt.date | None = None

    _as_of_not_future = field_validator("as_of")(_not_future)


def _set_balance(db: Session, account: Account, cents: int, day: dt.date) -> None:
    snap = db.scalar(select(BalanceSnapshot).where(BalanceSnapshot.account_id == account.id, BalanceSnapshot.date == day))
    if snap is None:
        db.add(BalanceSnapshot(account_id=account.id, date=day, balance_cents=cents))
    else:
        snap.balance_cents = cents


@router.post("", response_model=AccountOut, status_code=201)
def create_manual_account(body: ManualAccountIn, db: Session = Depends(get_db)):
    account = Account(external_id=f"manual-{uuid.uuid4().hex}", institution=body.institution, name=body.name,
                      type=body.type, is_manual=True)
    db.add(account)
    db.flush()
    _set_balance(db, account, body.balance_cents, body.as_of or dt.date.today())
    db.commit()
    return _out(account, _latest_snapshots(db).get(account.id))


@router.post("/{account_id}/balance", response_model=AccountOut)
def update_manual_balance(account_id: Id, body: BalanceIn, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    if not account.is_manual:
        raise HTTPException(422, "Only manual accounts take a balance update; synced balances come from SimpleFIN")
    _set_balance(db, account, body.balance_cents, body.as_of or dt.date.today())
    db.commit()
    return _out(account, _latest_snapshots(db).get(account.id))


@router.delete("/{account_id}", status_code=204)
def delete_manual_account(account_id: Id, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    if not account.is_manual:
        raise HTTPException(409, "Close or hide synced accounts instead")
    db.delete(account)
    db.commit()
    return Response(status_code=204)
