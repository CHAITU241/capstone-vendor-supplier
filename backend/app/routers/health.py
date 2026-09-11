from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.metrics import set_dependency_status
from app.schemas import HealthResponse
from app.vector_store import get_chroma_client

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
        database_status = "connected"
    except SQLAlchemyError:
        database_status = "disconnected"
    set_dependency_status("postgresql", database_status == "connected")

    try:
        get_chroma_client().heartbeat()
        chroma_status = "connected"
    except Exception:
        chroma_status = "disconnected"
    set_dependency_status("chroma", chroma_status == "connected")

    return HealthResponse(
        status=(
            "healthy"
            if database_status == "connected" and chroma_status == "connected"
            else "degraded"
        ),
        database=database_status,
        chroma=chroma_status,
    )
