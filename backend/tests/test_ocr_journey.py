from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app
from app.models import AuditEvent


def scanned_png(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=900, height=300)
    page.insert_text((60, 140), text, fontsize=28)
    image = page.get_pixmap(dpi=200, alpha=False).tobytes("png")
    document.close()
    return image


def test_supplier_can_retry_a_failed_scan_after_ocr_becomes_available(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ocr_state = {"enabled": False}

    def db_override():
        with Session(engine) as db:
            yield db

    def settings_override() -> Settings:
        return Settings(
            upload_dir=tmp_path / "uploads",
            chroma_path=tmp_path / "chroma",
            ocr_enabled=ocr_state["enabled"],
        )

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_settings] = settings_override
    try:
        with TestClient(app) as client:
            signup = client.post("/api/portal/auth/register", json={
                "email": "ocr@example.com",
                "password": "demo-password",
            })
            headers = {"Authorization": f"Bearer {signup.json()['token']}"}
            saved = client.patch("/api/portal/application", headers=headers, json={
                "category": "GOODS",
                "subcategory": "GOODS-OFF",
                "name": "Scanned Supplier Private Limited",
                "contact_email": "ocr@example.com",
                "tax_reference": "DEMO-PAN-OCR",
                "bank_account_number": "990000000001",
                "bank_ifsc": "DEMO0001234",
            })
            assert saved.status_code == 200, saved.text

            uploaded = client.post(
                "/api/portal/application/documents",
                headers=headers,
                data={"document_type": "registration"},
                files={"file": (
                    "registration-scan.png",
                    scanned_png("SCANNED SUPPLIER PRIVATE LIMITED"),
                    "image/png",
                )},
            )
            assert uploaded.status_code == 201, uploaded.text
            failed = uploaded.json()
            assert failed["processing_status"] == "failed"
            assert "OCR is disabled" in failed["error_message"]

            ocr_state["enabled"] = True
            retried = client.post(
                f"/api/portal/application/documents/{failed['id']}/text-extraction/retry",
                headers=headers,
            )
            assert retried.status_code == 200, retried.text
            recovered = retried.json()
            assert recovered["processing_status"] == "ready"
            assert recovered["text_extraction_method"] == "ocr"
            assert recovered["ocr_pages"] == [1]
            assert recovered["ocr_language"] == "eng"

            with Session(engine) as db:
                actions = db.scalars(select(AuditEvent.action)).all()
                assert "document.failed" in actions
                assert "document.text_extraction_retried" in actions
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
