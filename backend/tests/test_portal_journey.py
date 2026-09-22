"""The supplier draft survives sign-out and becomes visible only on submission."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from pathlib import Path
from uuid import UUID

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app
from app.models import DocumentRevision, ExtractedField, Supplier


def test_supplier_can_resume_and_submit_without_ai(tmp_path):
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_settings] = lambda: Settings(upload_dir=tmp_path / "uploads", chroma_path=tmp_path / "chroma")
    try:
        with TestClient(app) as client:
            signup = client.post("/api/portal/auth/register", json={"email": "SAMPLE@EXAMPLE.COM", "password": "demo-password"})
            assert signup.status_code == 201, signup.text
            supplier_headers = {"Authorization": f"Bearer {signup.json()['token']}"}
            assert client.get("/api/suppliers", headers=supplier_headers).status_code == 403

            saved = client.patch("/api/portal/application", headers=supplier_headers, json={
                "category": "GOODS", "subcategory": "GOODS-OFF",
            })
            assert saved.status_code == 200, saved.text
            assert saved.json()["submitted_at"] is None
            outside_scope = client.patch("/api/portal/application", headers=supplier_headers, json={
                "category": "GOODS", "subcategory": "GOODS-OFF", "name": "Example Supply Ltd", "country": "France",
            })
            assert outside_scope.status_code == 422
            assert client.post("/api/portal/auth/logout", headers=supplier_headers).status_code == 204

            login = client.post("/api/portal/auth/login", json={"email": "sample@example.com", "password": "demo-password"})
            assert login.status_code == 200, login.text
            supplier_headers = {"Authorization": f"Bearer {login.json()['token']}"}
            assert client.get("/api/portal/application", headers=supplier_headers).json()["subcategory"] == "GOODS-OFF"

            reviewer = client.post("/api/portal/auth/reviewer-demo")
            reviewer_headers = {"Authorization": f"Bearer {reviewer.json()['token']}"}
            assert client.get("/api/suppliers", headers=reviewer_headers).json() == []

            details = client.patch("/api/portal/application", headers=supplier_headers, json={
                "category": "GOODS", "subcategory": "GOODS-OFF",
                "name": "Example Supply Ltd", "contact_email": "sample@example.com",
                "tax_reference": "DEMO-PAN-123", "bank_account_number": "DEMO-ACCOUNT-123", "bank_ifsc": "DEMO0123456",
            })
            assert details.status_code == 200, details.text
            assert details.json()["country"] == "India"
            for kind in ("registration", "tax", "bank"):
                response = client.post("/api/portal/application/documents", headers=supplier_headers,
                    data={"document_type": kind}, files={"file": (f"{kind}.txt", b"Example Supply Ltd in India", "text/plain")})
                assert response.status_code == 201, response.text
            submitted = client.post("/api/portal/application/submit", headers=supplier_headers)
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["submitted_at"] is not None
            assert submitted.json()["status"] == "needs_review"
            cases = client.get("/api/suppliers", headers=reviewer_headers).json()
            assert len(cases) == 1 and cases[0]["category"] == "GOODS"
            assert client.patch("/api/portal/application", headers=supplier_headers, json={
                "category": "GOODS", "subcategory": "GOODS-ITE",
            }).status_code == 409
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_human_review_gates_approval_and_retains_erp_payload(tmp_path):
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_settings] = lambda: Settings(upload_dir=tmp_path / "uploads", chroma_path=tmp_path / "chroma")
    try:
        with TestClient(app) as client:
            account = client.post("/api/portal/auth/register", json={
                "email": "review-gate@example.com", "password": "demo-password",
            }).json()
            supplier_headers = {"Authorization": f"Bearer {account['token']}"}
            profile = client.patch("/api/portal/application", headers=supplier_headers, json={
                "category": "GOODS", "subcategory": "GOODS-OFF", "name": "Review Gate Supplies Ltd",
                "contact_email": "review-gate@example.com", "tax_reference": "DEMO-PAN-900",
                "bank_account_number": "DEMO-ACCOUNT-900", "bank_ifsc": "DEMO0123456",
            }).json()
            for kind in ("registration", "tax", "bank"):
                response = client.post("/api/portal/application/documents", headers=supplier_headers,
                    data={"document_type": kind},
                    files={"file": (f"{kind}.txt", b"Review Gate Supplies Ltd", "text/plain")})
                assert response.status_code == 201, response.text
            submitted = client.post("/api/portal/application/submit", headers=supplier_headers)
            assert submitted.status_code == 200, submitted.text
            supplier_id = UUID(profile["id"])

            with Session(engine) as db:
                supplier = db.get(Supplier, supplier_id)
                for document in supplier.documents:
                    document.redacted_text = document.extracted_text
                    document.redaction_summary = {}
                registration = next(item for item in supplier.documents if item.document_type.value == "registration")
                supplier.extracted_fields = [
                    ExtractedField(document=registration, field_name="supplier_name", value=supplier.name,
                                   page_number=1, confidence=0.97, needs_review=False, review_status="pending"),
                    ExtractedField(document=registration, field_name="contact_email", value=supplier.contact_email,
                                   page_number=1, confidence=0.96, needs_review=False, review_status="pending"),
                    ExtractedField(document=registration, field_name="country", value="India",
                                   page_number=1, confidence=0.98, needs_review=False, review_status="pending"),
                ]
                db.commit()

            reviewer = client.post("/api/portal/auth/reviewer-demo").json()
            review_headers = {"Authorization": f"Bearer {reviewer['token']}"}
            approve_url = f"/api/suppliers/{supplier_id}/approve"
            blocked = client.post(approve_url, headers=review_headers, json={
                "confirmed": True, "reviewer_name": "Demo reviewer",
            })
            assert blocked.status_code == 409

            detail = client.get(f"/api/suppliers/{supplier_id}", headers=review_headers).json()
            for document in detail["documents"]:
                reviewed = client.post(
                    f"/api/suppliers/{supplier_id}/documents/{document['id']}/review",
                    headers=review_headers, json={"action": "verify", "reviewer_name": "Demo reviewer"},
                )
                assert reviewed.status_code == 200, reviewed.text
            field_ids = [field["id"] for field in detail["extracted_fields"]]
            reviewed_fields = client.post(f"/api/suppliers/{supplier_id}/fields/review", headers=review_headers,
                json={"ids": field_ids, "action": "verify", "reviewer_name": "Demo reviewer"})
            assert reviewed_fields.status_code == 200, reviewed_fields.text

            approved = client.post(approve_url, headers=review_headers, json={
                "confirmed": True, "reviewer_name": "Demo reviewer",
            })
            assert approved.status_code == 200, approved.text
            assert approved.json()["erp_supplier_id"].startswith("ERP-")
            final = client.get(f"/api/suppliers/{supplier_id}", headers=review_headers).json()
            assert final["erp_payload"]["legal_name"] == "Review Gate Supplies Ltd"
            assert final["erp_payload"]["tax_reference"] == "DEMO-PAN-900"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_originals_are_private_and_retained_after_replacement(tmp_path):
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_settings] = lambda: Settings(upload_dir=tmp_path / "uploads", chroma_path=tmp_path / "chroma")
    try:
        with TestClient(app) as client:
            first_account = client.post("/api/portal/auth/register", json={"email": "original@example.com", "password": "demo-password"})
            other_account = client.post("/api/portal/auth/register", json={"email": "other@example.com", "password": "demo-password"})
            own = {"Authorization": f"Bearer {first_account.json()['token']}"}
            other = {"Authorization": f"Bearer {other_account.json()['token']}"}
            reviewer = client.post("/api/portal/auth/reviewer-demo")
            review = {"Authorization": f"Bearer {reviewer.json()['token']}"}
            profile = client.patch("/api/portal/application", headers=own, json={
                "category": "GOODS", "subcategory": "GOODS-OFF", "name": "Original Supply Ltd",
                "contact_email": "original@example.com", "tax_reference": "DEMO-PAN-1",
                "bank_account_number": "DEMO-ACCOUNT-1", "bank_ifsc": "DEMO0123456",
            })
            assert profile.status_code == 200, profile.text
            supplier_id = profile.json()["id"]
            url = "/api/portal/application/documents"
            upload = client.post(url, headers=own, data={"document_type": "registration"},
                files={"file": ("first.txt", b"Original Supply Ltd, first version", "text/plain")})
            assert upload.status_code == 201, upload.text
            first_id = upload.json()["id"]
            assert upload.json()["revision"] == 1
            assert len(upload.json()["sha256"]) == 64
            assert client.get(f"{url}/{first_id}/content", headers=own).content == b"Original Supply Ltd, first version"
            assert client.get(f"{url}/{first_id}/content", headers=other).status_code == 404
            assert client.get(f"/api/suppliers/{supplier_id}/documents/{first_id}/content", headers=review).status_code == 404

            assert client.delete(f"{url}/{first_id}", headers=own).status_code == 204
            history = client.get(f"{url}/history", headers=own).json()
            assert [item["id"] for item in history] == [first_id]
            assert client.get(f"{url}/{first_id}/content", headers=own).content == b"Original Supply Ltd, first version"
            assert client.get(f"{url}/{first_id}/content", headers=other).status_code == 404

            replacement = client.post(url, headers=own, data={"document_type": "registration"},
                files={"file": ("second.txt", b"Original Supply Ltd, second version", "text/plain")})
            assert replacement.status_code == 201, replacement.text
            assert replacement.json()["revision"] == 2
            assert replacement.json()["id"] != first_id
            for kind in ("tax", "bank"):
                response = client.post(url, headers=own, data={"document_type": kind},
                    files={"file": (f"{kind}.txt", b"Original Supply Ltd", "text/plain")})
                assert response.status_code == 201, response.text
            assert client.post("/api/portal/application/submit", headers=own).status_code == 200
            reviewer_url = f"/api/suppliers/{supplier_id}/documents"
            assert client.get(f"{reviewer_url}/{first_id}/content", headers=review).content == b"Original Supply Ltd, first version"
            assert client.get(f"{reviewer_url}/history", headers=review).json()[0]["revision"] == 1
            with Session(engine) as db:
                archived = db.get(DocumentRevision, UUID(first_id))
                Path(archived.storage_path).write_bytes(b"altered outside the portal")
            assert client.get(f"{reviewer_url}/{first_id}/content", headers=review).status_code == 409
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_checklist_changes_with_profile_and_is_frozen_on_submission(tmp_path):
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_settings] = lambda: Settings(upload_dir=tmp_path / "uploads")
    try:
        with TestClient(app) as client:
            signup = client.post("/api/portal/auth/register", json={"email": "software@example.com", "password": "demo-password"})
            headers = {"Authorization": f"Bearer {signup.json()['token']}"}
            profile = {"category": "TECH", "subcategory": "TECH-CYB", "name": "Example Software Ltd", "country": "India",
                       "contact_email": "software@example.com", "tax_reference": "DEMO-PAN-456",
                       "bank_account_number": "DEMO-ACCOUNT-456", "bank_ifsc": "DEMO0123456"}
            first = client.patch("/api/portal/application", headers=headers, json=profile)
            assert [item["requirement_id"] for item in first.json()["requirements"]["documents"]] == [
                "BASE-001", "BASE-002", "BASE-003", "CONF-001", "SEC-001", "PRIV-001", "CONT-001", "INS-CYB-001"]
            cyber = client.post("/api/portal/application/documents", headers=headers,
                data={"document_type": "INS-CYB-001"}, files={"file": ("cyber.txt", b"Example Software Ltd", "text/plain")})
            assert cyber.status_code == 201, cyber.text

            profile.update(subcategory="TECH-SW")
            changed = client.patch("/api/portal/application", headers=headers, json=profile)
            assert [item["document_type"] for item in changed.json()["requirements"]["documents"]] == [
                "registration", "tax", "bank", "CONF-001", "SEC-001", "PRIV-001", "CONT-001"]
            assert client.post("/api/portal/application/documents", headers=headers,
                data={"document_type": "INS-CYB-001"}, files={"file": ("another.txt", b"Example", "text/plain")}).status_code == 422

            for kind in ("registration", "tax", "bank", "CONF-001", "SEC-001", "PRIV-001", "CONT-001"):
                uploaded = client.post("/api/portal/application/documents", headers=headers,
                    data={"document_type": kind}, files={"file": (f"{kind}.txt", b"Example Software Ltd", "text/plain")})
                assert uploaded.status_code == 201, uploaded.text
            assert client.post("/api/portal/application/submit", headers=headers).status_code == 422
            assert client.delete(f"/api/portal/application/documents/{cyber.json()['id']}", headers=headers).status_code == 204
            submitted = client.post("/api/portal/application/submit", headers=headers)
            assert submitted.status_code == 200, submitted.text
            assert len(submitted.json()["requirements"]["documents"]) == 7

            with Session(engine) as db:
                supplier = db.get(Supplier, UUID(submitted.json()["id"]))
                supplier.category = "GOODS"  # Simulate a later policy/profile edit.
                db.commit()

            reviewer = client.post("/api/portal/auth/reviewer-demo").json()
            reviewer_headers = {"Authorization": f"Bearer {reviewer['token']}"}
            detail = client.get(f"/api/suppliers/{submitted.json()['id']}", headers=reviewer_headers)
            assert len(detail.json()["requirements"]["documents"]) == 7
            # With seven ready documents, AI processing reaches the provider check.
            assert client.post(f"/api/suppliers/{submitted.json()['id']}/process", headers=reviewer_headers).status_code == 503
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
