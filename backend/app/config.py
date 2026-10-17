"""Settings from the repo-root .env. Read as `config.X` at call time so tests can monkeypatch."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(PROJECT_DIR / ".env")


def env_path(name: str, default: Path) -> Path:
    """An unset or blank variable falls back to the default; Path("") would mean the current directory."""
    return Path(os.getenv(name, "").strip() or default).expanduser()


SIMPLEFIN_TOKEN = os.getenv("SIMPLEFIN_TOKEN", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")  # used from M5
DB_PATH = env_path("DB_PATH", BACKEND_DIR / "monarch-lite.db")
BACKUP_DIR = env_path("BACKUP_DIR", Path.home() / "monarch-lite-backups")
FRONTEND_DIST = env_path("FRONTEND_DIST", PROJECT_DIR / "frontend" / "dist")
