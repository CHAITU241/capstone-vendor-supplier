from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ErpRecordRead
from app.services.erp_mcp_client import ErpMcpClient
from app.services.erp_tools import ErpToolFailure
from app.services.portal_auth import require_reviewer

router = APIRouter(prefix="/mock-erp", tags=["mock-erp"], dependencies=[Depends(require_reviewer)])


@router.get("/records", response_model=list[ErpRecordRead])
def list_erp_records(db: Session = Depends(get_db)) -> list[ErpRecordRead]:
    try:
        result = ErpMcpClient().call(db, "list_supplier_records", {})
    except ErpToolFailure as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    return [ErpRecordRead(**record) for record in result["records"]]
