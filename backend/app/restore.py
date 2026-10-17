"""Restore the database from a backup (FR-DATA-03). Usage: python -m app.restore <backup.db>"""
import contextlib
import datetime as dt
import os
import shutil
import socket
import sqlite3
import sys
from pathlib import Path

from . import config
from .services.backup import STAMP


class RestoreError(Exception):
    pass


def server_running(port: int = 8000) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def restore(backup_file: Path, db_path: Path) -> Path | None:
    try:
        with contextlib.closing(sqlite3.connect(f"file:{backup_file}?mode=ro", uri=True)) as conn:
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            has_tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 0
    except sqlite3.DatabaseError as exc:
        raise RestoreError(f"{backup_file} is not a valid SQLite database: {exc}") from exc
    if not ok:
        raise RestoreError(f"{backup_file} failed its integrity check")
    if not has_tables:
        raise RestoreError(f"{backup_file} contains no tables")
    safety = None
    if db_path.exists():
        # online backup API, not a file copy: it includes pages still sitting in the WAL
        safety = db_path.with_name(f"{db_path.name}.pre-restore-{dt.datetime.now().strftime(STAMP)}")
        with contextlib.closing(sqlite3.connect(db_path)) as live, contextlib.closing(sqlite3.connect(safety)) as dst:
            live.backup(dst)
    for suffix in ("-wal", "-shm"):  # stale WAL files would be replayed over the restored copy
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    staged = db_path.with_name(db_path.name + ".restore-tmp")  # same directory, so the replace is atomic
    try:
        shutil.copy2(backup_file, staged)
        os.replace(staged, db_path)
    finally:
        staged.unlink(missing_ok=True)
    return safety


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.restore <backup.db>")
        return 2
    if server_running():
        print("monarch-lite is still running on port 8000. Stop it first: launchctl bootout gui/$(id -u)/com.monarch-lite")
        return 1
    try:
        safety = restore(Path(argv[1]).expanduser(), config.DB_PATH)
    except RestoreError as exc:
        print(exc)
        return 1
    kept = f" (previous copy kept as {safety.name})" if safety else ""
    print(f"Restored {argv[1]} -> {config.DB_PATH}{kept}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
