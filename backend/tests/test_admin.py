"""Admin maintenance must stay separate from supplier and reviewer sessions."""

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app
from app.models import AiRun, AiRunStatus, AiRunType, Document, DocumentRevision, ErpToolAttempt, PortalAccount, Supplier


def test_admin_reset_and_full_profile_removal(tmp_path, monkeypatch):
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    deleted_vectors = []
    monkeypatch.setattr("app.routers.admin.get_chunk_collection", lambda: object())
    monkeypatch.setattr("app.routers.admin.delete_supplier_chunks", lambda _, supplier_id: deleted_vectors.append(supplier_id))

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path / "uploads", chroma_path=tmp_path / "chroma",
        admin_auth_enabled=True,
        admin_email="owner@example.com", admin_password="strong-admin-password",
    )
    try:
        with TestClient(app) as client:
            supplier = client.post("/api/portal/auth/register", json={"email": "supplier@example.com", "password": "original-pass"}).json()
            own = {"Authorization": f"Bearer {supplier['token']}"}
            reviewer = client.post("/api/portal/auth/reviewer-demo").json()
            review = {"Authorization": f"Bearer {reviewer['token']}"}
            assert client.get("/api/admin/profiles", headers=own).status_code == 403
            assert client.get("/api/admin/profiles", headers=review).status_code == 403
            assert client.get("/api/admin/observability", headers=own).status_code == 403
            assert client.get("/api/admin/observability", headers=review).status_code == 403
            assert client.post("/api/portal/auth/admin", json={"email": "owner@example.com", "password": "wrong-password"}).status_code == 401
            admin = client.post("/api/portal/auth/admin", json={"email": "owner@example.com", "password": "strong-admin-password"})
            assert admin.status_code == 200
            access = {"Authorization": f"Bearer {admin.json()['token']}"}
            profile = client.get("/api/admin/profiles", headers=access).json()[0]
            assert profile["email"] == "supplier@example.com"
            supplier_id = profile["id"]
            assert client.patch("/api/portal/application", headers=own, json={
                "category": "GOODS", "subcategory": "GOODS-OFF", "name": "Demo supplier",
            }).status_code == 200
            upload = client.post("/api/portal/application/documents", headers=own,
                data={"document_type": "registration"},
                files={"file": ("first.txt", b"original", "text/plain")})
            assert upload.status_code == 201, upload.text
            first_id = upload.json()["id"]
            assert client.delete(f"/api/portal/application/documents/{first_id}", headers=own).status_code == 204
            second = client.post("/api/portal/application/documents", headers=own,
                data={"document_type": "registration"},
                files={"file": ("second.txt", b"replacement", "text/plain")})
            assert second.status_code == 201, second.text
            listed = client.get("/api/admin/profiles", headers=access).json()[0]
            assert (listed["document_count"], listed["archived_count"]) == (1, 1)

            with Session(engine) as db:
                db.add(AiRun(
                    supplier_id=UUID(supplier_id), run_type=AiRunType.QUESTION,
                    status=AiRunStatus.SUCCEEDED, model="openai/gpt-4o-mini",
                    prompt_version="rag-answer-v3", input_tokens=120,
                    output_tokens=30, latency_ms=850, retrieval_count=3,
                    details={"information_found": True, "citation_count": 1,
                             "grounding_guard_passed": True},
                ))
                db.add(ErpToolAttempt(
                    supplier_id=UUID(supplier_id), operation="validate_supplier_record",
                    status="succeeded", latency_ms=20,
                ))
                db.commit()
            metrics = client.get("/api/admin/observability", headers=access)
            assert metrics.status_code == 200, metrics.text
            summary = metrics.json()
            assert summary["total_runs"] == 1
            assert summary["input_tokens"] == 120
            assert summary["output_tokens"] == 30
            assert summary["success_rate"] == 100.0
            assert summary["grounded_answers"] == 1
            assert summary["erp_attempts"] == 1
            assert summary["erp_failures"] == 0
            assert summary["recent_runs"][0]["supplier_reference"].startswith("SUP-")

            changed = client.post(f"/api/admin/profiles/{supplier_id}/reset-password", headers=access)
            assert changed.status_code == 200
            assert changed.json()["password"] != "original-pass"
            assert client.get("/api/portal/application", headers=own).status_code == 401
            assert client.post("/api/portal/auth/login", json={"email": "supplier@example.com", "password": "original-pass"}).status_code == 401
            assert client.post("/api/portal/auth/login", json={"email": "supplier@example.com", "password": changed.json()["password"]}).status_code == 200

            assert client.delete(f"/api/admin/profiles/{supplier_id}", headers=review).status_code == 403
            assert client.delete(f"/api/admin/profiles/{supplier_id}", headers=access).status_code == 204
            assert deleted_vectors == [supplier_id]
            assert not (tmp_path / "uploads" / supplier_id).exists()
            assert client.get("/api/admin/profiles", headers=access).json() == []
            with Session(engine) as db:
                assert db.get(Supplier, UUID(supplier_id)) is None
                assert db.scalars(select(PortalAccount)).all() == []
                assert db.scalars(select(Document)).all() == []
                assert db.scalars(select(DocumentRevision)).all() == []
            assert client.post("/api/portal/auth/login", json={"email": "supplier@example.com", "password": changed.json()["password"]}).status_code == 401
            reviewer_created = client.post("/api/suppliers", headers=review, json={"name": "Internal demo", "country": "India"})
            assert reviewer_created.status_code == 201, reviewer_created.text
            profiles = client.get("/api/admin/profiles", headers=access).json()
            assert len(profiles) == 1 and profiles[0]["email"] is None
            assert client.post(f"/api/admin/profiles/{reviewer_created.json()['id']}/reset-password", headers=access).status_code == 404
            assert client.delete(f"/api/admin/profiles/{reviewer_created.json()['id']}", headers=access).status_code == 204
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
