"""Bulk confirmation only verifies requirements that are genuinely ready."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    AuditEvent,
    ComplianceResult,
    ComplianceStatus,
    Document,
    ExtractedField,
    ProcessingStatus,
    Supplier,
    SupplierStatus,
)
from app.services.document_policy import checklist_for


@pytest.mark.parametrize("attention_reason", ["document", "ocr", "field"])
def test_confirm_ready_requirements_excludes_manual_attention_and_audits_batch(tmp_path, attention_reason):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path / "uploads",
        chroma_path=tmp_path / "chroma",
    )
    try:
        with Session(engine) as db:
            supplier = Supplier(
                name="Bulk Confirmation Supplies Ltd",
                country="India",
                contact_email="bulk@example.com",
                tax_reference="BULK-PAN-1",
                bank_account_number="990000000001",
                bank_ifsc="DEMO0123456",
                category="GOODS",
                subcategory="GOODS-OFF",
                status=SupplierStatus.NEEDS_REVIEW,
            )
            checklist = checklist_for(supplier)
            supplier.requirements_snapshot = checklist.model_dump(mode="json")
            supplier.submitted_at = datetime.now(UTC)
            db.add(supplier)
            db.flush()

            attention_document_id = None
            expected_confirmed_ids = []
            for index, requirement in enumerate(checklist.documents):
                document = Document(
                    supplier_id=supplier.id,
                    document_type=requirement.document_type,
                    filename=f"{requirement.document_type.value}.txt",
                    storage_path=f"test/{requirement.document_type.value}.txt",
                    content_type="text/plain",
                    file_size=32,
                    page_count=1,
                    extracted_text="Bulk Confirmation Supplies Ltd",
                    redacted_text="Bulk Confirmation Supplies Ltd",
                    processing_status=ProcessingStatus.READY,
                    ai_extraction_status="ready",
                    ai_index_status="ready",
                    review_status="attention" if index == 0 and attention_reason == "document" else "pending",
                    ocr_quality_status="review" if index == 0 and attention_reason == "ocr" else None,
                )
                db.add(document)
                db.flush()
                if index == 0:
                    attention_document_id = document.id
                else:
                    expected_confirmed_ids.append(document.id)
                db.add(ExtractedField(
                    supplier_id=supplier.id,
                    document_id=document.id,
                    field_name="supplier_name",
                    value=supplier.name,
                    page_number=1,
                    confidence=0.98,
                    needs_review=index == 0 and attention_reason == "field",
                    review_status="pending",
                ))
                for check_number in (1, 2):
                    db.add(ComplianceResult(
                        supplier_id=supplier.id,
                        rule_code=f"{requirement.requirement_id}.CHECK-{check_number}",
                        status=ComplianceStatus.PASS,
                        message="The extracted evidence matches the policy check.",
                        evidence={
                            "kind": "policy_check",
                            "requirement_id": requirement.requirement_id,
                            "document_id": str(document.id),
                            "check_number": check_number,
                            "ai_assessment": "matched",
                        },
                    ))
            db.commit()
            supplier_id = supplier.id

        with TestClient(app) as client:
            reviewer = client.post("/api/portal/auth/reviewer-demo")
            assert reviewer.status_code == 200, reviewer.text
            headers = {"Authorization": f"Bearer {reviewer.json()['token']}"}
            confirmed = client.post(
                f"/api/suppliers/{supplier_id}/requirements/confirm-ready",
                headers=headers,
                json={"reviewer_name": "Batch Reviewer"},
            )
            assert confirmed.status_code == 200, confirmed.text
            assert confirmed.json()["confirmed_count"] == len(expected_confirmed_ids)
            assert set(confirmed.json()["document_ids"]) == {
                str(document_id) for document_id in expected_confirmed_ids
            }

            repeated = client.post(
                f"/api/suppliers/{supplier_id}/requirements/confirm-ready",
                headers=headers,
                json={"reviewer_name": "Batch Reviewer"},
            )
            assert repeated.status_code == 409

        with Session(engine) as db:
            documents = db.scalars(
                select(Document).where(Document.supplier_id == supplier_id)
            ).all()
            confirmed_documents = [
                document for document in documents if document.id in expected_confirmed_ids
            ]
            attention_document = db.get(Document, attention_document_id)
            assert all(document.review_status == "verified" for document in confirmed_documents)
            assert all(document.reviewed_by == "Batch Reviewer" for document in confirmed_documents)
            assert attention_document is not None
            assert attention_document.review_status == ("attention" if attention_reason == "document" else "pending")

            fields = db.scalars(
                select(ExtractedField).where(ExtractedField.supplier_id == supplier_id)
            ).all()
            assert all(
                field.review_status == "verified" and not field.needs_review
                for field in fields
                if field.document_id in expected_confirmed_ids
            )
            attention_field = next(
                field for field in fields if field.document_id == attention_document_id
            )
            assert attention_field.review_status == "pending"
            assert attention_field.needs_review == (attention_reason == "field")

            audits = db.scalars(
                select(AuditEvent).where(AuditEvent.supplier_id == supplier_id)
            ).all()
            batch = next(
                event for event in audits
                if event.action == "reviewer.ready_requirements.bulk_confirmed"
            )
            assert batch.details["confirmed_count"] == len(expected_confirmed_ids)
            document_audits = [event for event in audits if event.action == "document.verified"]
            assert len(document_audits) == len(expected_confirmed_ids)
            assert all(event.details["bulk_action"] for event in document_audits)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
