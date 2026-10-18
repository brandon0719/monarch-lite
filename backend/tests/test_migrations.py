import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from app import seed

BACKEND = Path(__file__).resolve().parents[1]


def _alembic(*args, db_path):
    env = {**os.environ, "DB_PATH": str(db_path)}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True)


def test_upgrade_seeds_and_downgrade_removes_everything(tmp_path):
    db_path = tmp_path / "migrate.db"
    _alembic("upgrade", "head", db_path=db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT count(*) FROM categories").fetchone()[0] == len(seed.CATEGORIES)
    assert conn.execute("SELECT count(*) FROM rules").fetchone()[0] == len(seed.KEYWORD_RULES)
    conn.close()
    _alembic("downgrade", "base", db_path=db_path)
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert tables <= {"alembic_version"}


def test_budget_settings_table_and_no_schema_drift(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from app import models  # noqa: F401  (registers every table on Base.metadata)
    from app.db import Base

    db_path = tmp_path / "drift.db"
    _alembic("upgrade", "head", db_path=db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='budget_settings'").fetchone()
    conn.close()
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert diff == []


def test_classic_migration_moves_rent_bucket_and_drops_rent_cents(tmp_path):
    db_path = tmp_path / "classic.db"
    _alembic("upgrade", "745c340b56e1", db_path=db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE categories SET bucket='rent' WHERE name='Rent'")
    conn.execute("INSERT INTO budget_settings (id, take_home_cents, rent_cents, needs_pct, wants_pct, savings_pct, updated_at) "
                 "VALUES (1, 730000, 120000, 50, 30, 20, '2026-10-16 00:00:00')")
    conn.commit()
    conn.close()
    _alembic("upgrade", "head", db_path=db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT count(*) FROM categories WHERE bucket='rent'").fetchone()[0] == 0
    assert conn.execute("SELECT bucket FROM categories WHERE name='Rent'").fetchone()[0] == "needs"
    columns = {r[1] for r in conn.execute("PRAGMA table_info(budget_settings)")}
    assert "rent_cents" not in columns
    assert conn.execute("SELECT take_home_cents FROM budget_settings WHERE id=1").fetchone()[0] == 730000
    conn.close()


_BEFORE_MANUAL = "5d0a2e97994b"
_CHILD_TABLES = ("accounts", "balance_snapshots", "transactions", "transaction_tags", "rules", "recurring_items")


def _seed_populated(db_path):
    """Synthetic rows hanging off `accounts` (and categories) that a table rebuild with FKs ON would cascade away."""
    conn = sqlite3.connect(db_path)
    groceries = conn.execute("SELECT id FROM categories WHERE name='Groceries'").fetchone()[0]
    conn.execute("INSERT INTO accounts (id, external_id, institution, name, type, is_hidden) "
                 "VALUES (901, 'acc-test-1', 'Test Bank', 'Test Checking', 'checking', 0)")
    conn.execute("INSERT INTO balance_snapshots (account_id, date, balance_cents) VALUES (901, '2026-10-01', 123456)")
    conn.execute("INSERT INTO transactions (id, account_id, external_id, posted_date, amount_cents, raw_description, "
                 "merchant, merchant_locked, category_id, category_source, created_at) VALUES "
                 "(801, 901, 'txn-test-1', '2026-10-02', -4200, 'TEST MARKET', 'Test Market', 0, ?, 'manual', "
                 "'2026-10-02 00:00:00')", (groceries,))
    conn.execute("INSERT INTO tags (id, name) VALUES (701, 'test-tag')")
    conn.execute("INSERT INTO transaction_tags (transaction_id, tag_id) VALUES (801, 701)")
    conn.execute("INSERT INTO rules (priority, contains_text, account_id, set_category_id) VALUES (5, 'TEST MARKET', 901, ?)",
                 (groceries,))
    conn.execute("INSERT INTO recurring_items (merchant, name, amount_cents, cadence, anchor_date, category_id, created_at) "
                 "VALUES ('Test Gym', 'Test Gym', -2500, 'monthly', '2026-10-05', ?, '2026-10-05 00:00:00')", (groceries,))
    conn.commit()
    conn.close()
    return groceries


def _counts(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in _CHILD_TABLES}
        counts["scoped_rules"] = conn.execute("SELECT count(*) FROM rules WHERE account_id=901").fetchone()[0]
        counts["txn_category"] = conn.execute("SELECT max(category_id) FROM transactions WHERE id=801").fetchone()[0]
    return counts


def test_populated_db_survives_upgrade_and_stepwise_downgrade(tmp_path):
    db_path = tmp_path / "populated.db"
    _alembic("upgrade", _BEFORE_MANUAL, db_path=db_path)
    groceries = _seed_populated(db_path)
    before = _counts(db_path)
    assert before["scoped_rules"] == 1 and before["txn_category"] == groceries

    _alembic("upgrade", "head", db_path=db_path)
    assert _counts(db_path) == before
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT is_manual FROM accounts WHERE id=901").fetchone()[0] == 0

    for _ in range(2):  # head -> ceb50a8ccf06 -> 5d0a2e97994b, one step at a time
        _alembic("downgrade", "-1", db_path=db_path)
        assert _counts(db_path) == before
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == _BEFORE_MANUAL
        assert "is_manual" not in {r[1] for r in conn.execute("PRAGMA table_info(accounts)")}


_FK_PROBE = """
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

seen = []
original = MigrationContext.run_migrations
def probe(self, **kw):
    seen.append(self.connection.exec_driver_sql("PRAGMA foreign_keys").scalar())
    original(self, **kw)
    seen.append(self.connection.exec_driver_sql("PRAGMA foreign_keys").scalar())
MigrationContext.run_migrations = probe
command.upgrade(Config("alembic.ini"), "head")
print(seen)
"""


def test_migrations_run_with_foreign_keys_off(tmp_path):
    """A future batch rebuild of a parent table must never cascade-delete its children."""
    env = {**os.environ, "DB_PATH": str(tmp_path / "fk.db")}
    out = subprocess.run([sys.executable, "-c", _FK_PROBE], cwd=BACKEND, env=env, check=True,
                         capture_output=True, text=True).stdout
    assert out.strip().splitlines()[-1] == "[0, 0]"
