from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    AuditEvent, ComplianceResult, ComplianceStatus, Document, DocumentRevision,
    DocumentType, Supplier, SupplierStatus,
)
from app.services.document_policy import extraction_field_names
from app.services.openai_service import (
    DocumentExtraction,
    ExtractedValue,
    ModelResult,
    PolicyCheckAssessment,
    ReviewerFlagReason,
)
from app.services.upload_validation import names_are_plausibly_same


class FakeUploadAI:
    def __init__(self, state: dict[str, str]):
        self.state = state

    def extract_document(self, expected_type: DocumentType, filename: str, redacted_text: str):
        mode = self.state.get("mode", "pass")
        classified = DocumentType.TAX if mode == "wrong_type" else expected_type
        values = {
            "supplier_name": "Example Supply Private Limited",
            "tax_identifier": "ABCDE1234F",
            "bank_account_number": "990000000069",
            "bank_ifsc": "DEMO0001234",
        }
        if mode == "name_mismatch":
            values["supplier_name"] = "Unrelated Trading Company Limited"
        elif mode == "tax_mismatch":
            values["tax_identifier"] = "ZZZZZ9999Z"
        elif mode == "account_mismatch":
            values["bank_account_number"] = "880000000069"
        elif mode == "ifsc_mismatch":
            values["bank_ifsc"] = "WRNG0001234"
        fields = []
        for field_name in extraction_field_names(expected_type):
            if mode == "missing_fields" and field_name != "supplier_name":
                value = None
            else:
                value = values.get(field_name, "Present")
            fields.append(ExtractedValue(
                field_name=field_name,
                value=value,
                page_number=1,
                confidence=0.98,
            ))
        return ModelResult(
            value=DocumentExtraction(
                classified_document_type=classified,
                fields=fields,
                policy_checks=[
                    PolicyCheckAssessment(
                        check_number=1, result="matched", reason="The required evidence is present.",
                        evidence_fields=[], page_number=1,
                    ),
                    PolicyCheckAssessment(
                        check_number=2, result="human_review", reason="A reviewer confirms authenticity.",
                        evidence_fields=[], page_number=1,
                    ),
                ],
            ),
            input_tokens=100,
            output_tokens=50,
        )


class FakeFlagAI:
    def draft_reviewer_flag_reason(self, *, finding_context: str, policy_context: str):
        assert "account number" in finding_context.casefold()
        assert policy_context
        return ModelResult(
            value=ReviewerFlagReason(reason=(
                "Please replace the bank account evidence. The account number does not match "
                "the portal details, so upload a current bank document for the same supplier."
            )),
            input_tokens=80,
            output_tokens=30,
        )


def test_name_matching_tolerates_small_ocr_noise_but_rejects_another_entity() -> None:
    assert names_are_plausibly_same(
        "Indigo Office Supply 069 Pvt Ltd", "Indigo Office Supply 69 Private Limited",
    )
    assert not names_are_plausibly_same(
        "Indigo Office Supply Private Limited", "Unrelated Trading Company Limited",
    )


@pytest.fixture
def upload_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    state = {"mode": "pass"}
    settings = Settings(
        upload_dir=tmp_path / "uploads",
        chroma_path=tmp_path / "chroma",
        upload_ai_validation_enabled=True,
    )

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(
        "app.routers.documents.build_openai_service",
        lambda _: FakeUploadAI(state),
    )
    try:
        with TestClient(app) as client:
            account = client.post("/api/portal/auth/register", json={
                "email": "validation@example.com", "password": "demo-password",
            }).json()
            headers = {"Authorization": f"Bearer {account['token']}"}
            profile = client.patch("/api/portal/application", headers=headers, json={
                "category": "GOODS",
                "subcategory": "GOODS-OFF",
                "name": "Example Supply Private Limited",
                "contact_email": "validation@example.com",
                "tax_reference": "ABCDE1234F",
                "bank_account_number": "990000000069",
                "bank_ifsc": "DEMO0001234",
            }).json()
            yield client, headers, profile, engine, settings, state
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def upload(client: TestClient, headers: dict, kind: str, content: bytes = b"Complete supplier evidence"):
    return client.post(
        "/api/portal/application/documents",
        headers=headers,
        data={"document_type": kind},
        files={"file": (f"{kind}.txt", content, "text/plain")},
    )


def test_passing_file_is_promoted_and_extraction_is_reused(upload_app) -> None:
    client, headers, _, engine, settings, _ = upload_app
    response = upload(client, headers, "bank")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["upload_validation_status"] == "passed"
    assert body["ai_extraction_status"] == "ready"
    with Session(engine) as db:
        document = db.scalar(select(Document))
        assert document is not None
        assert Path(document.storage_path).is_file()
        assert {field.field_name for field in document.extracted_fields} >= {
            "supplier_name", "bank_account_number", "bank_ifsc",
        }
        assert document.upload_validation_details["model"] == settings.active_extraction_model
        assert all(
            item["document_id"] == str(document.id)
            for item in document.upload_validation_details["policy_assessments"]
        )
        assert db.scalar(select(AuditEvent).where(
            AuditEvent.action == "document.accepted_after_validation"
        )) is not None


@pytest.mark.parametrize(
    ("kind", "mode", "expected"),
    [
        ("registration", "wrong_type", "Wrong document type"),
        ("registration", "name_mismatch", "Supplier/legal name mismatch"),
        ("tax", "tax_mismatch", "Pan/tax reference mismatch"),
        ("bank", "account_mismatch", "Bank account number mismatch"),
        ("bank", "ifsc_mismatch", "Ifsc mismatch"),
        ("registration", "missing_fields", "Expected information could not be found"),
    ],
)
def test_invalid_upload_is_rejected_without_a_permanent_document(
    upload_app, kind: str, mode: str, expected: str,
) -> None:
    client, headers, _, engine, settings, state = upload_app
    state["mode"] = mode
    response = upload(client, headers, kind)
    assert response.status_code == 422, response.text
    assert expected.casefold() in response.json()["message"].casefold()
    with Session(engine) as db:
        assert db.scalars(select(Document)).all() == []
        rejection = db.scalar(select(AuditEvent).where(
            AuditEvent.action == "document.upload_rejected"
        ))
        assert rejection is not None
        assert rejection.details["permanent_file_created"] is False
    permanent_files = [
        path for path in settings.upload_dir.rglob("*")
        if path.is_file() and ".staging" not in path.parts
    ]
    assert permanent_files == []


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "status_code", "message"),
    [
        ("empty.txt", b"", "text/plain", 400, "Empty file"),
        ("malware.exe", b"not evidence", "application/octet-stream", 415, "Unsupported file type"),
        ("broken.pdf", b"not a PDF", "application/pdf", 422, "Unreadable file"),
        ("large.txt", b"x" * (10 * 1024 * 1024 + 1), "text/plain", 413, "Oversized file"),
    ],
)
def test_basic_file_rejections_are_specific_and_not_persisted(
    upload_app, filename: str, content: bytes, content_type: str,
    status_code: int, message: str,
) -> None:
    client, headers, _, engine, _, _ = upload_app
    response = client.post(
        "/api/portal/application/documents",
        headers=headers,
        data={"document_type": "registration"},
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == status_code, response.text
    assert message in response.json()["message"]
    with Session(engine) as db:
        assert db.scalars(select(Document)).all() == []


def test_failed_replacement_keeps_current_flagged_document(upload_app) -> None:
    client, headers, profile, engine, _, state = upload_app
    accepted = upload(client, headers, "bank")
    assert accepted.status_code == 201, accepted.text
    original_id = accepted.json()["id"]
    with Session(engine) as db:
        supplier = db.get(Supplier, UUID(profile["id"]))
        supplier.submitted_at = datetime.now(UTC)
        supplier.status = SupplierStatus.NEEDS_REVIEW
        document = db.get(Document, UUID(original_id))
        document.review_status = "disputed"
        document.review_comment = "The account number does not match."
        db.commit()

    state["mode"] = "account_mismatch"
    replacement = upload(client, headers, "bank", b"Replacement evidence")
    assert replacement.status_code == 422, replacement.text
    with Session(engine) as db:
        active = db.scalars(select(Document)).all()
        assert [str(item.id) for item in active] == [original_id]
        assert active[0].review_status == "disputed"
        assert db.scalars(select(DocumentRevision)).all() == []


def test_reviewer_receives_editable_ai_rag_flag_draft(
    upload_app, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, headers, profile, engine, settings, _ = upload_app
    accepted = upload(client, headers, "bank")
    assert accepted.status_code == 201, accepted.text
    document_id = accepted.json()["id"]
    with Session(engine) as db:
        db.add(ComplianceResult(
            supplier_id=UUID(profile["id"]),
            rule_code="BASE-003.CHECK-1",
            status=ComplianceStatus.FAIL,
            message="The bank account number does not match the portal payment field.",
            evidence={
                "kind": "policy_check",
                "document_id": document_id,
                "requirement_id": "BASE-003",
                "check_number": 1,
                "ai_reason": "The bank account number does not match.",
            },
        ))
        db.commit()
    settings.openrouter_api_key = SecretStr("test-key")
    monkeypatch.setattr("app.routers.review.build_openai_service", lambda _: FakeFlagAI())
    reviewer = client.post("/api/portal/auth/reviewer-demo").json()
    response = client.post(
        f"/api/suppliers/{profile['id']}/documents/{document_id}/flag-reason-draft",
        headers={"Authorization": f"Bearer {reviewer['token']}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "ai_rag"
    assert response.json()["finding_count"] == 1
    assert "account number does not match" in response.json()["reason"].casefold()
