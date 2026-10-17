"""Daily SQLite backups (FR-DATA-02). Uses SQLite's online backup API, safe while the app runs."""
import contextlib
import datetime as dt
import os
import sqlite3
from pathlib import Path

PREFIX = "monarch-lite-"
STAMP = "%Y%m%d-%H%M%S"
KEEP = 30


def _stamped(backup_dir: Path) -> list[tuple[dt.datetime, Path]]:
    """Backups whose names parse as PREFIX + STAMP + .db, oldest first. Foreign files are ignored."""
    found = []
    for p in backup_dir.glob(f"{PREFIX}*.db"):
        try:
            found.append((dt.datetime.strptime(p.stem.removeprefix(PREFIX), STAMP), p))
        except ValueError:
            continue
    return sorted(found)


def backup(db_path: Path, backup_dir: Path, now: dt.datetime | None = None, keep: int = KEEP) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"{PREFIX}{(now or dt.datetime.now()).strftime(STAMP)}.db"
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        # mode=ro: a missing source raises instead of silently creating an empty database
        with contextlib.closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as src, contextlib.closing(
            sqlite3.connect(tmp)
        ) as dst:
            src.backup(dst)
        os.replace(tmp, dest)  # the real name only ever holds a complete backup
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    for _, old in _stamped(backup_dir)[:-keep]:
        old.unlink()
    return dest


def newest_backup_age(backup_dir: Path, now: dt.datetime | None = None) -> dt.timedelta | None:
    stamps = _stamped(backup_dir)
    return (now or dt.datetime.now()) - stamps[-1][0] if stamps else None
