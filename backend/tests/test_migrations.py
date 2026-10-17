import os
import sqlite3
import subprocess
import sys
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
