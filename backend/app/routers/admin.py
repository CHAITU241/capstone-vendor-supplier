"""Small, separately authenticated maintenance workspace for demo profiles."""

import secrets
import shutil
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import AiRun, AiRunStatus, Document, DocumentRevision, ErpSupplierRecord, ErpToolAttempt, PortalAccount, PortalSession, Supplier, SupplierStatus
from app.services.portal_auth import hash_password, require_admin
from app.services.retrieval import delete_supplier_chunks, get_chunk_collection

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class AdminProfile(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None
    status: SupplierStatus
    created_at: datetime
    submitted_at: datetime | None
    document_count: int
    archived_count: int


class NewPassword(BaseModel):
    password: str


class AdminMetricGroup(BaseModel):
    label: str
    calls: int
    input_tokens: int
    output_tokens: int
    average_latency_ms: int
    failures: int


class AdminRecentRun(BaseModel):
    id: uuid.UUID
    supplier_reference: str
    run_type: str
    status: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    retrieval_count: int
    created_at: datetime


class AdminObservability(BaseModel):
    generated_at: datetime
    window_days: int
    provider: str
    extraction_model: str
    answer_model: str
    embedding_model: str
    ai_configured: bool
    langfuse_enabled: bool
    langfuse_configured: bool
    langfuse_content_capture: bool
    langfuse_dashboard_url: str | None
    total_runs: int
    successful_runs: int
    failed_runs: int
    in_progress_runs: int
    success_rate: float
    input_tokens: int
    output_tokens: int
    average_latency_ms: int
    p95_latency_ms: int
    question_runs: int
    grounded_answers: int
    guarded_not_found_answers: int
    average_retrieval_count: float
    documents: int
    native_documents: int
    ocr_assisted_documents: int
    failed_text_extractions: int
    ocr_pages: int
    erp_attempts: int
    erp_failures: int
    erp_average_latency_ms: int
    by_model: list[AdminMetricGroup]
    by_operation: list[AdminMetricGroup]
    by_prompt_version: list[AdminMetricGroup]
    recent_runs: list[AdminRecentRun]


@router.get("/profiles", response_model=list[AdminProfile])
def list_profiles(db: Session = Depends(get_db)) -> list[AdminProfile]:
    active = select(func.count(Document.id)).where(Document.supplier_id == Supplier.id).scalar_subquery()
    archived = select(func.count(DocumentRevision.id)).where(DocumentRevision.supplier_id == Supplier.id).scalar_subquery()
    rows = db.execute(select(Supplier, PortalAccount.email, active, archived)
                      .outerjoin(PortalAccount, Supplier.account_id == PortalAccount.id)
                      .order_by(Supplier.created_at.desc())).all()
    return [AdminProfile(id=supplier.id, name=supplier.name, email=email,
                         status=supplier.status, created_at=supplier.created_at,
                         submitted_at=supplier.submitted_at, document_count=count,
                         archived_count=history) for supplier, email, count, history in rows]


def _metric_groups(runs: list[AiRun], label_for) -> list[AdminMetricGroup]:
    grouped: dict[str, list[AiRun]] = defaultdict(list)
    for run in runs:
        grouped[str(label_for(run))].append(run)
    return [
        AdminMetricGroup(
            label=label,
            calls=len(items),
            input_tokens=sum(item.input_tokens for item in items),
            output_tokens=sum(item.output_tokens for item in items),
            average_latency_ms=round(sum(item.latency_ms for item in items) / len(items)),
            failures=sum(item.status == AiRunStatus.FAILED for item in items),
        )
        for label, items in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0]))
    ]


@router.get("/observability", response_model=AdminObservability)
def observability(
    days: int = Query(default=30, ge=0, le=3650),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AdminObservability:
    """Return privacy-safe operational summaries for the admin workspace."""

    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    run_query = select(AiRun).order_by(AiRun.created_at.desc())
    document_query = select(Document)
    erp_query = select(ErpToolAttempt)
    if cutoff is not None:
        run_query = run_query.where(AiRun.created_at >= cutoff)
        document_query = document_query.where(Document.created_at >= cutoff)
        erp_query = erp_query.where(ErpToolAttempt.created_at >= cutoff)
    runs = list(db.scalars(run_query).all())
    documents = list(db.scalars(document_query).all())
    erp_attempts = list(db.scalars(erp_query).all())

    successful = sum(run.status == AiRunStatus.SUCCEEDED for run in runs)
    failed = sum(run.status == AiRunStatus.FAILED for run in runs)
    in_progress = sum(run.status == AiRunStatus.PROCESSING for run in runs)
    latencies = sorted(run.latency_ms for run in runs)
    p95_latency = latencies[max(0, ceil(len(latencies) * 0.95) - 1)] if latencies else 0
    question_runs = [run for run in runs if run.run_type.value == "question"]
    grounded_answers = sum(
        run.status == AiRunStatus.SUCCEEDED and bool(
            run.details.get("grounding_guard_passed", (
                not run.details.get("information_found") or bool(run.details.get("model_cited_labels"))
            ))
        )
        for run in question_runs
    )
    guarded_not_found = sum(
        run.status == AiRunStatus.SUCCEEDED and not bool(run.details.get("information_found"))
        for run in question_runs
    )
    erp_latencies = [attempt.latency_ms for attempt in erp_attempts]
    langfuse_secret = (
        settings.langfuse_secret_key.get_secret_value().strip()
        if settings.langfuse_secret_key else ""
    )
    langfuse_configured = bool(
        settings.langfuse_enabled
        and settings.langfuse_public_key
        and langfuse_secret
    )

    return AdminObservability(
        generated_at=datetime.now(timezone.utc),
        window_days=days,
        provider=settings.ai_provider,
        extraction_model=settings.active_extraction_model,
        answer_model=settings.active_answer_model,
        embedding_model=settings.active_embedding_model,
        ai_configured=settings.ai_configured,
        langfuse_enabled=settings.langfuse_enabled,
        langfuse_configured=langfuse_configured,
        langfuse_content_capture=settings.langfuse_capture_content,
        langfuse_dashboard_url=(settings.langfuse_dashboard_url or settings.langfuse_base_url)
            if langfuse_configured else None,
        total_runs=len(runs),
        successful_runs=successful,
        failed_runs=failed,
        in_progress_runs=in_progress,
        success_rate=round(successful / (successful + failed) * 100, 1)
            if successful + failed else 0,
        input_tokens=sum(run.input_tokens for run in runs),
        output_tokens=sum(run.output_tokens for run in runs),
        average_latency_ms=round(sum(latencies) / len(latencies)) if latencies else 0,
        p95_latency_ms=p95_latency,
        question_runs=len(question_runs),
        grounded_answers=grounded_answers,
        guarded_not_found_answers=guarded_not_found,
        average_retrieval_count=round(
            sum(run.retrieval_count for run in question_runs) / len(question_runs), 2
        ) if question_runs else 0,
        documents=len(documents),
        native_documents=sum(document.text_extraction_method == "native" for document in documents),
        ocr_assisted_documents=sum(document.text_extraction_method in {"ocr", "mixed"} for document in documents),
        failed_text_extractions=sum(document.processing_status.value == "failed" for document in documents),
        ocr_pages=sum(len(document.ocr_pages or []) for document in documents),
        erp_attempts=len(erp_attempts),
        erp_failures=sum(attempt.status != "succeeded" for attempt in erp_attempts),
        erp_average_latency_ms=round(sum(erp_latencies) / len(erp_latencies)) if erp_latencies else 0,
        by_model=_metric_groups(runs, lambda run: run.model),
        by_operation=_metric_groups(runs, lambda run: run.run_type.value),
        by_prompt_version=_metric_groups(runs, lambda run: run.prompt_version),
        recent_runs=[
            AdminRecentRun(
                id=run.id,
                supplier_reference=f"SUP-{str(run.supplier_id).split('-')[0].upper()}",
                run_type=run.run_type.value,
                status=run.status.value,
                model=run.model,
                prompt_version=run.prompt_version,
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                latency_ms=run.latency_ms,
                retrieval_count=run.retrieval_count,
                created_at=run.created_at,
            )
            for run in runs[:15]
        ],
    )


@router.post("/profiles/{supplier_id}/reset-password", response_model=NewPassword)
def reset_password(supplier_id: uuid.UUID, response: Response, db: Session = Depends(get_db)) -> NewPassword:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or supplier.account_id is None:
        raise HTTPException(status_code=404, detail="This profile has no supplier login.")
    account = db.get(PortalAccount, supplier.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Supplier login was not found.")
    password = secrets.token_urlsafe(24)
    account.password_hash = hash_password(password)
    db.execute(delete(PortalSession).where(PortalSession.account_id == account.id))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return NewPassword(password=password)


@router.delete("/profiles/{supplier_id}", status_code=204)
def delete_profile(supplier_id: uuid.UUID, db: Session = Depends(get_db),
                   settings: Settings = Depends(get_settings)) -> Response:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier profile was not found.")

    # Uploaded originals live only inside this supplier's UUID directory.
    upload_root = settings.upload_dir.resolve()
    directory = upload_root / str(supplier_id)
    if directory.is_symlink():
        raise HTTPException(status_code=409, detail="Supplier file storage needs inspection.")
    paths = db.scalars(select(Document.storage_path).where(Document.supplier_id == supplier_id)).all()
    paths += db.scalars(select(DocumentRevision.storage_path).where(DocumentRevision.supplier_id == supplier_id)).all()
    if any(not Path(path).resolve().is_relative_to(directory) for path in paths):
        raise HTTPException(status_code=409, detail="Supplier file storage needs inspection.")

    # Clear vector records before deleting the relational profile. A vector-store
    # failure leaves the profile available so deletion can be retried.
    delete_supplier_chunks(get_chunk_collection(), str(supplier_id))
    db.execute(delete(ErpToolAttempt).where(ErpToolAttempt.supplier_id == supplier_id))
    db.execute(delete(ErpSupplierRecord).where(ErpSupplierRecord.source_supplier_id == supplier_id))
    db.execute(delete(DocumentRevision).where(DocumentRevision.supplier_id == supplier_id))
    account = db.get(PortalAccount, supplier.account_id) if supplier.account_id else None
    if account:
        db.execute(delete(PortalSession).where(PortalSession.account_id == account.id))
    db.delete(supplier)
    db.flush()
    if account:
        db.delete(account)
    db.commit()
    if directory.exists():
        shutil.rmtree(directory)
    return Response(status_code=204)
