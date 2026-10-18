"""M5 round 1: RSU grants, vest calendar and value (FR-RSU-01, FR-RSU-03)."""
import datetime as dt
from typing import Literal, get_args

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import RsuGrant, RsuVest
from ..services import prices, rsu
from .params import MAX_DAY, Day, Id

router = APIRouter(prefix="/api/rsu", tags=["rsu"])
Schedule = Literal["amazon_5_15_40_40", "semiannual", "custom"]
if set(get_args(Schedule)) != set(rsu.SCHEDULES):  # an explicit raise survives `python -O`
    raise RuntimeError("router schedules out of sync with services.rsu")
MAX_SHARES = 1_000_000


class VestIn(BaseModel):
    vest_date: Day
    shares: int = Field(ge=1, le=MAX_SHARES)


class GrantIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=100)
    external_id: str | None = Field(None, max_length=64)
    symbol: str = Field("AMZN", min_length=1, max_length=16)
    grant_date: Day
    start_date: Day
    total_shares: int = Field(ge=1, le=MAX_SHARES)
    schedule: Schedule
    first_vest: Day | None = None
    count: int | None = Field(None, ge=1, le=rsu.MAX_SEMIANNUAL)
    vests: list[VestIn] | None = Field(None, max_length=100)

    @field_validator("symbol")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class GrantPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    label: str | None = Field(None, min_length=1, max_length=100)
    external_id: str | None = Field(None, max_length=64)


class VestsIn(BaseModel):
    vests: list[VestIn] = Field(min_length=1, max_length=100)


class PriceOut(BaseModel):
    symbol: str
    price_cents: int
    as_of: dt.datetime
    source: str


class VestOut(BaseModel):
    id: int
    vest_date: dt.date
    shares: int
    vested: bool
    value_cents: int | None


class GrantOut(BaseModel):
    id: int
    label: str
    external_id: str | None
    symbol: str
    grant_date: dt.date
    start_date: dt.date
    total_shares: int
    schedule: str
    vested_shares: int
    unvested_shares: int
    unvested_value_cents: int | None
    vests: list[VestOut]


class NextVest(BaseModel):
    vest_date: dt.date
    shares: int
    value_cents: int | None
    grant_label: str


class Totals(BaseModel):
    unvested_shares: int
    unvested_value_cents: int | None
    vested_shares: int
    next_vest: NextVest | None


class RsuOut(BaseModel):
    price: PriceOut | None
    grants: list[GrantOut]
    totals: Totals


def _get(db: Session, grant_id: int) -> RsuGrant:
    grant = db.get(RsuGrant, grant_id)
    if grant is None:
        raise HTTPException(404, "Grant not found")
    return grant


def _value(shares: int, price_cents: int | None) -> int | None:
    return None if price_cents is None else shares * price_cents


def _grant_out(grant: RsuGrant, price_cents: int | None, today: dt.date) -> GrantOut:
    vests = [VestOut(id=v.id, vest_date=v.vest_date, shares=v.shares, vested=v.vest_date <= today,
                     value_cents=_value(v.shares, price_cents)) for v in grant.vests]
    vested = sum(v.shares for v in vests if v.vested)
    return GrantOut(
        id=grant.id, label=grant.label, external_id=grant.external_id, symbol=grant.symbol,
        grant_date=grant.grant_date, start_date=grant.start_date, total_shares=grant.total_shares,
        schedule=grant.schedule, vested_shares=vested, unvested_shares=grant.total_shares - vested,
        unvested_value_cents=_value(grant.total_shares - vested, price_cents) if grant.total_shares > vested else 0,
        vests=vests,
    )


def _single(db: Session, grant: RsuGrant) -> GrantOut:
    quote = prices.cached_price(db, grant.symbol)  # only GET may trigger a fetch
    return _grant_out(grant, quote[0] if quote else None, dt.date.today())


def _vest_rows(vests: list[VestIn]) -> list[tuple[dt.date, int]]:
    return [(v.vest_date, v.shares) for v in vests]


@router.get("", response_model=RsuOut)
def get_rsu(db: Session = Depends(get_db)):
    today = dt.date.today()
    grants = list(db.scalars(select(RsuGrant).order_by(RsuGrant.grant_date, RsuGrant.id)))
    quotes = {symbol: prices.get_price(db, symbol) for symbol in dict.fromkeys(g.symbol for g in grants)}
    outs = [_grant_out(g, quotes[g.symbol][0] if quotes[g.symbol] else None, today) for g in grants]
    symbols = [g.symbol for g in grants]
    shown = "AMZN" if "AMZN" in symbols else (symbols[0] if symbols else None)
    quote = quotes.get(shown) if shown else None
    upcoming = [(v.vest_date, g.label, v) for g in outs for v in g.vests if not v.vested]
    nxt = min(upcoming, key=lambda t: t[:2], default=None)
    return RsuOut(
        price=PriceOut(symbol=shown, price_cents=quote[0], as_of=quote[1], source=quote[2]) if quote else None,
        grants=outs,
        totals=Totals(
            unvested_shares=sum(g.unvested_shares for g in outs),
            # Null unless every grant that still has unvested shares is priced: a partial sum would understate it.
            unvested_value_cents=None if not outs or any(g.unvested_value_cents is None for g in outs)
            else sum(g.unvested_value_cents for g in outs),
            vested_shares=sum(g.vested_shares for g in outs),
            next_vest=None if nxt is None else NextVest(vest_date=nxt[2].vest_date, shares=nxt[2].shares,
                                                        value_cents=nxt[2].value_cents, grant_label=nxt[1]),
        ),
    )


@router.post("/grants", response_model=GrantOut, status_code=201)
def create_grant(body: GrantIn, db: Session = Depends(get_db)):
    try:
        built = rsu.build_vests(body.schedule, body.start_date, body.total_shares, body.first_vest, body.count,
                                _vest_rows(body.vests or []))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if built and built[-1][0] > MAX_DAY:  # generated schedules can run past the last supported year
        raise HTTPException(422, f"Vests can't be later than {MAX_DAY.year}")
    grant = RsuGrant(
        label=body.label, external_id=body.external_id or None, symbol=body.symbol, grant_date=body.grant_date,
        start_date=body.start_date, total_shares=body.total_shares, schedule=body.schedule,
        vests=[RsuVest(vest_date=d, shares=s) for d, s in built],
    )
    db.add(grant)
    db.commit()
    return _single(db, grant)


@router.patch("/grants/{grant_id}", response_model=GrantOut)
def patch_grant(grant_id: Id, body: GrantPatch, db: Session = Depends(get_db)):
    grant = _get(db, grant_id)
    data = body.model_dump(exclude_unset=True)
    if "label" in data and data["label"] is None:
        raise HTTPException(422, "Label can't be empty")
    if "external_id" in data:
        data["external_id"] = data["external_id"] or None
    for key, value in data.items():
        setattr(grant, key, value)
    db.commit()
    return _single(db, grant)


@router.put("/grants/{grant_id}/vests", response_model=GrantOut)
def replace_vests(grant_id: Id, body: VestsIn, db: Session = Depends(get_db)):
    grant = _get(db, grant_id)
    if grant.schedule != "custom":
        raise HTTPException(422, "Only custom grants have editable vests")
    try:
        built = rsu.check_custom(_vest_rows(body.vests), grant.total_shares)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    grant.vests = [RsuVest(vest_date=d, shares=s) for d, s in built]
    db.commit()
    return _single(db, grant)


@router.delete("/grants/{grant_id}", status_code=204)
def delete_grant(grant_id: Id, db: Session = Depends(get_db)):
    db.delete(_get(db, grant_id))
    db.commit()
    return Response(status_code=204)
