"""M4: investment holdings and allocation (FR-NW-03, FR-NW-04)."""
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import DEFAULT_THRESHOLD, Account, AllocationTargets, AssetClass, Holding

router = APIRouter(prefix="/api", tags=["investments"])
CLASSES = ("stocks", "bonds", "cash")


def default_class(description: str) -> str:
    """Sweep/cash-equivalent positions are Cash; everything else defaults to Stocks."""
    return "cash" if "sweep" in description.lower() else "stocks"


def class_of(db: Session, symbol: str, description: str) -> str:
    override = db.get(AssetClass, symbol)
    return override.asset_class if override else default_class(description)


class HoldingOut(BaseModel):
    id: int
    account_id: int
    account_name: str
    symbol: str
    description: str
    shares: str
    price_cents: int | None
    market_value_cents: int
    cost_basis_cents: int | None
    gain_cents: int | None
    gain_pct: float | None
    asset_class: str
    as_of: dt.date


def visible_holdings(db: Session) -> list[Holding]:
    return list(db.scalars(
        select(Holding).join(Holding.account)
        .where(Account.is_hidden.is_(False), Account.closed_at.is_(None))
        .order_by(Account.name, Holding.market_value_cents.desc(), Holding.symbol)
    ))


def _price(h: Holding) -> int | None:
    try:
        shares = Decimal(h.shares)
        if not shares.is_finite() or shares == 0:
            return None
        return int((Decimal(h.market_value_cents) / shares).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (ValueError, ArithmeticError):
        return None


@router.get("/holdings", response_model=list[HoldingOut])
def list_holdings(db: Session = Depends(get_db)):
    out = []
    for h in visible_holdings(db):
        gain = None if h.cost_basis_cents is None else h.market_value_cents - h.cost_basis_cents
        out.append(HoldingOut(
            id=h.id, account_id=h.account_id, account_name=h.account.name, symbol=h.symbol, description=h.description,
            shares=h.shares, price_cents=_price(h), market_value_cents=h.market_value_cents,
            cost_basis_cents=h.cost_basis_cents, gain_cents=gain,
            gain_pct=None if gain is None or not h.cost_basis_cents else round(gain / h.cost_basis_cents, 4),
            asset_class=class_of(db, h.symbol, h.description), as_of=h.as_of,
        ))
    return out


AssetClassName = Literal["stocks", "bonds", "cash"]
Symbol = Annotated[str, Path(min_length=1, max_length=32)]
Pct = Annotated[int, Field(ge=0, le=100)]
TARGETS_ID = 1


class ClassIn(BaseModel):
    asset_class: AssetClassName


class ClassOut(BaseModel):
    symbol: str
    asset_class: str


class TargetsIn(BaseModel):
    stocks_pct: Pct
    bonds_pct: Pct
    cash_pct: Pct
    drift_threshold: int = Field(default=DEFAULT_THRESHOLD, ge=1, le=50)

    @model_validator(mode="after")
    def _sums(self):
        if self.stocks_pct + self.bonds_pct + self.cash_pct != 100:
            raise ValueError("Stocks + Bonds + Cash must add up to 100%")
        return self


class TargetsOut(BaseModel):
    configured: bool
    stocks_pct: int | None
    bonds_pct: int | None
    cash_pct: int | None
    drift_threshold: int


class ClassShare(BaseModel):
    asset_class: str
    value_cents: int
    pct: float
    target_pct: int | None
    drift_pts: float | None
    over: bool


class AllocationOut(BaseModel):
    configured: bool
    drift_threshold: int
    total_cents: int
    classes: list[ClassShare]


def _targets_out(t: AllocationTargets | None) -> TargetsOut:
    if t is None:
        return TargetsOut(configured=False, stocks_pct=None, bonds_pct=None, cash_pct=None,
                          drift_threshold=DEFAULT_THRESHOLD)
    return TargetsOut(configured=True, stocks_pct=t.stocks_pct, bonds_pct=t.bonds_pct, cash_pct=t.cash_pct,
                      drift_threshold=t.drift_threshold)


# {symbol:path}: tickers like BRK/B arrive as BRK%2FB, which Starlette decodes before routing
@router.put("/holdings/classes/{symbol:path}", response_model=ClassOut)
def set_class(symbol: Symbol, body: ClassIn, db: Session = Depends(get_db)):
    symbol = symbol.strip()
    if not symbol:
        raise HTTPException(422, "Symbol can't be blank")
    row = db.get(AssetClass, symbol) or AssetClass(symbol=symbol)
    row.asset_class = body.asset_class
    db.add(row)
    db.commit()
    return ClassOut(symbol=symbol, asset_class=body.asset_class)


@router.get("/allocation/targets", response_model=TargetsOut)
def get_targets(db: Session = Depends(get_db)):
    return _targets_out(db.get(AllocationTargets, TARGETS_ID))


@router.put("/allocation/targets", response_model=TargetsOut)
def put_targets(body: TargetsIn, db: Session = Depends(get_db)):
    row = db.get(AllocationTargets, TARGETS_ID) or AllocationTargets(id=TARGETS_ID)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    db.add(row)
    db.commit()
    return _targets_out(row)


@router.get("/allocation", response_model=AllocationOut)
def get_allocation(db: Session = Depends(get_db)):
    values = dict.fromkeys(CLASSES, 0)
    for h in visible_holdings(db):
        values[class_of(db, h.symbol, h.description)] += h.market_value_cents
    total = sum(values.values())
    targets = db.get(AllocationTargets, TARGETS_ID)
    threshold = targets.drift_threshold if targets else DEFAULT_THRESHOLD
    shares = []
    for name in CLASSES:
        pct = round(values[name] / total, 4) if total else 0.0
        target = getattr(targets, f"{name}_pct") if targets else None
        drift = None if target is None else round(pct * 100 - target, 1)
        shares.append(ClassShare(asset_class=name, value_cents=values[name], pct=pct, target_pct=target,
                                 drift_pts=drift, over=drift is not None and abs(drift) > threshold))
    return AllocationOut(configured=targets is not None, drift_threshold=threshold, total_cents=total, classes=shares)
