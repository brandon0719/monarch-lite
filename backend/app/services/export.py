"""Full data export as CSV per table + one JSON file (FR-DATA-01)."""
import csv
import io
import json
import zipfile

from sqlalchemy import text
from sqlalchemy.orm import Session

TABLES = (
    "accounts", "balance_snapshots", "transactions", "tags", "transaction_tags", "categories", "rules", "sync_runs",
    "budget_settings", "category_budgets", "recurring_items", "recurring_dismissals",
    "goals", "goal_accounts", "goal_contributions",
)


def export_zip(db: Session) -> bytes:
    buf, everything = io.BytesIO(), {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for table in TABLES:  # constant names, never user input
            result = db.execute(text(f"SELECT * FROM {table}"))
            columns, rows = list(result.keys()), [list(r) for r in result]
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(columns)
            writer.writerows(rows)
            archive.writestr(f"{table}.csv", out.getvalue())
            everything[table] = [dict(zip(columns, r)) for r in rows]
        archive.writestr("export.json", json.dumps(everything, default=str, indent=2))
    return buf.getvalue()
