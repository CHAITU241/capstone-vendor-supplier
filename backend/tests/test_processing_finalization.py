"""First processing and refresh share findings, OCR controls and atomic completion."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Base
from app.models import (
    AiRun, AiRunStatus, ComplianceResult, Document, DocumentType,
    ExtractedField, ProcessingStatus, Supplier, SupplierStatus,
)
from app.services.openai_service import DocumentExtraction, ExtractedValue, ModelResult, PolicyCheckAssessment
from app.services.processing import process_supplier_documents


@pytest.mark.parametrize("refresh", [False, True])
@pytest.mark.parametrize("quality", ["good", "review"])
@pytest.mark.parametrize("index_status", ["pending", "ready"])
def test_processing_publishes_checks_with_completion_and_preserves_ocr_gate(
    tmp_path, monkeypatch, refresh, quality, index_status,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'processing.db'}")
    Base.metadata.create_all(engine)
    values = {
        "supplier_name": "Example Supply Private Limited",
        "registration_number": "REG-001",
        "issuing_registry": "Demo Registry",
        "registration_date": "2026-01-01",
        "status": "Active",
    }

    class FakeAI:
        def extract_document(self, **kwargs):
            return ModelResult(
                value=DocumentExtraction(
                    classified_document_type=DocumentType.REGISTRATION,
                    fields=[ExtractedValue(field_name=name, value=value,
                                           page_number=1, confidence=0.98)
                            for name, value in values.items()],
                    policy_checks=[PolicyCheckAssessment(
                        check_number=number, result="human_review",
                        reason="Model opinion must not replace the objective date check.",
                        evidence_fields=["registration_date"], page_number=1,
                    ) for number in (1, 2)],
                ), input_tokens=10, output_tokens=10,
            )

        def embed(self, texts):
            return SimpleNamespace(embeddings=[[1.0] for _ in texts], input_tokens=5)

    monkeypatch.setattr("app.services.processing.chunk_document", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.services.processing.replace_document_chunks", lambda **kwargs: None)

    with Session(engine, autoflush=False, expire_on_commit=False) as db:
        supplier = Supplier(name=values["supplier_name"], country="India",
                            category="GOODS", subcategory="GOODS-OFF",
                            status=SupplierStatus.PROCESSING)
        db.add(supplier)
        db.flush()
        document = Document(
            supplier_id=supplier.id, document_type=DocumentType.REGISTRATION,
            filename="registration.png", storage_path="registration.png",
            content_type="image/png", file_size=100, page_count=1,
            extracted_text="[Page 1] Example Supply Private Limited 2026-01-01 Active",
            processing_status=ProcessingStatus.READY, ai_extraction_status="ready",
            ai_index_status=index_status, text_extraction_method="ocr",
            ocr_quality_status=quality, ocr_quality_score=65 if quality == "review" else 95,
            review_status="attention" if quality == "review" else "pending",
        )
        db.add(document)
        db.flush()
        for name, value in values.items():
            db.add(ExtractedField(
                supplier_id=supplier.id, document_id=document.id, field_name=name,
                value=value, page_number=1, confidence=0.98,
                needs_review=quality == "review",
                review_status="attention" if quality == "review" else "pending",
            ))
        db.commit()
        supplier_id = supplier.id
        completed_snapshots = []

        def assert_completion_has_current_checks(session):
            with Session(engine) as observer:
                run = observer.scalar(select(AiRun).where(
                    AiRun.supplier_id == supplier_id,
                    AiRun.status == AiRunStatus.SUCCEEDED,
                ))
                if run is None:
                    return
                check = observer.scalar(select(ComplianceResult).where(
                    ComplianceResult.supplier_id == supplier_id,
                    ComplianceResult.rule_code == "BASE-001.CHECK-2",
                ))
                assert check is not None, "Completed run must never expose absent/stale findings"
                assert check.evidence["ai_assessment"] == "matched"
                assert check.evidence["evidence_requires_verification"] == (quality == "review")
                completed_snapshots.append(check.evidence["ai_assessment"])

        event.listen(db, "after_commit", assert_completion_has_current_checks)
        outcome = process_supplier_documents(db, supplier, Settings(), FakeAI(), None,
                                             force_reprocess=refresh)
        assert outcome.run.status == AiRunStatus.SUCCEEDED
        assert completed_snapshots == ["matched"]
        db.refresh(document)
        assert document.review_status == ("attention" if quality == "review" else "pending")
        stored_fields = db.scalars(select(ExtractedField).where(
            ExtractedField.document_id == document.id,
        )).all()
        assert all(item.needs_review == (quality == "review") for item in stored_fields)
    engine.dispose()
