"""FR-DATA-01 export, FR-DATA-02 backup on demand."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..services import backup as backup_service
from ..services.export import export_zip

router = APIRouter(prefix="/api", tags=["data"])


@router.post("/backups")
def backup_now() -> dict[str, str]:
    return {"path": str(backup_service.backup(config.DB_PATH, config.BACKUP_DIR))}


@router.get("/export")
def export(db: Session = Depends(get_db)) -> Response:
    return Response(
        export_zip(db),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="monarch-lite-export.zip"'},
    )
