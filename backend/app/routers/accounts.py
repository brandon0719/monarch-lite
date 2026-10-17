"""FR-ACC-04 status, FR-ACC-07 hide/close."""
import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, BalanceSnapshot

router = APIRouter(prefix="/api/accounts", tags=["accounts"])
AccountType = Literal["checking", "savings", "credit", "investment", "loan", "other"]


class AccountOut(BaseModel):
    id: int
    institution: str
    name: str
    type: str
    is_hidden: bool
    closed_at: dt.date | None
    last_synced_at: dt.datetime | None
    last_error: str | None
    balance_cents: int | None
    balance_date: dt.date | None


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
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
def patch_account(account_id: int, body: AccountPatch, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(account, key, value)
    db.commit()
    return _out(account, _latest_snapshots(db).get(account.id))
