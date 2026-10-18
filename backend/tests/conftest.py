import datetime as dt
import itertools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Account, Category, Transaction
from app.seed import seed_defaults


@pytest.fixture(autouse=True)
def _no_network_prices(monkeypatch, request):
    """config loads the real .env; tests must never call Finnhub.

    The blocked stub records every symbol it is asked for and the test FAILS at teardown if any got through,
    unless it opts in with @pytest.mark.allow_blocked_fetch (get_price swallows the stub's error otherwise)."""
    from app import config
    from app.services import prices

    monkeypatch.setattr(config, "FINNHUB_API_KEY", "")

    reached = []  # symbols that hit the blocked fetch, so an accidental call is visible

    def blocked(symbol):
        reached.append(symbol)
        raise AssertionError("tests must not fetch real prices")

    monkeypatch.setattr(prices, "finnhub_quote", blocked)
    prices.clear_failures()
    yield reached
    prices.clear_failures()
    if reached and request.node.get_closest_marker("allow_blocked_fetch") is None:
        pytest.fail(f"test reached the blocked Finnhub fetch for {reached}; inject a fetch or mark allow_blocked_fetch")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    seed_defaults(session)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    # No `with`: the lifespan (and so the hourly scheduler) never starts in tests.
    yield TestClient(app)
    app.dependency_overrides.clear()


_ids = itertools.count(1)


def make_account(db, name="Checking", type="checking", external_id=None, **kw) -> Account:
    account = Account(
        external_id=external_id or f"acc-{next(_ids)}",
        institution=kw.pop("institution", "Test Bank"),
        name=name,
        type=type,
        **kw,
    )
    db.add(account)
    db.commit()
    return account


def make_txn(
    db, account, amount_cents, posted_date=dt.date(2026, 10, 1), raw_description="TEST MERCHANT", external_id=None, **kw
) -> Transaction:
    txn = Transaction(
        account=account,
        external_id=external_id or f"txn-{next(_ids)}",
        posted_date=posted_date,
        amount_cents=amount_cents,
        raw_description=raw_description,
        merchant=kw.pop("merchant", raw_description),
        **kw,
    )
    db.add(txn)
    db.commit()
    return txn


def category(db, name) -> Category:
    return db.scalar(select(Category).where(Category.name == name))
