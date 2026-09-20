"""The supplier draft survives sign-out and becomes visible only on submission."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app


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
                "category": "Technology & IT", "subcategory": "Software & SaaS",
            })
            assert saved.status_code == 200, saved.text
            assert saved.json()["submitted_at"] is None
            assert client.post("/api/portal/auth/logout", headers=supplier_headers).status_code == 204

            login = client.post("/api/portal/auth/login", json={"email": "sample@example.com", "password": "demo-password"})
            assert login.status_code == 200, login.text
            supplier_headers = {"Authorization": f"Bearer {login.json()['token']}"}
            assert client.get("/api/portal/application", headers=supplier_headers).json()["subcategory"] == "Software & SaaS"

            reviewer = client.post("/api/portal/auth/reviewer-demo")
            reviewer_headers = {"Authorization": f"Bearer {reviewer.json()['token']}"}
            assert client.get("/api/suppliers", headers=reviewer_headers).json() == []

            details = client.patch("/api/portal/application", headers=supplier_headers, json={
                "category": "Technology & IT", "subcategory": "Software & SaaS",
                "name": "Example Supply Ltd", "country": "India", "contact_email": "sample@example.com",
            })
            assert details.status_code == 200, details.text
            for kind in ("registration", "tax", "insurance"):
                response = client.post("/api/portal/application/documents", headers=supplier_headers,
                    data={"document_type": kind}, files={"file": (f"{kind}.txt", b"Example Supply Ltd in India", "text/plain")})
                assert response.status_code == 201, response.text
            submitted = client.post("/api/portal/application/submit", headers=supplier_headers)
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["submitted_at"] is not None
            cases = client.get("/api/suppliers", headers=reviewer_headers).json()
            assert len(cases) == 1 and cases[0]["category"] == "Technology & IT"
            assert client.patch("/api/portal/application", headers=supplier_headers, json={
                "category": "Goods & materials", "subcategory": "Equipment",
            }).status_code == 409
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
