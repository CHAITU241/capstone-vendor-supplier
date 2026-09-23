from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app
from app.models import ComplianceResult, ComplianceStatus, Document, DocumentType, ExtractedField, ProcessingStatus, Supplier
from app.services.openai_service import ModelResult, ReviewerAssistantAnswer


class EmptyCollection:
    def get(self, **_kwargs):
        return {"ids": []}


def test_reviewer_assistant_receives_case_state_and_keeps_separate_history(tmp_path, monkeypatch):
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    contexts: list[str] = []
    conversations: list[list[dict[str, str]]] = []

    class FakeAssistant:
        def answer_reviewer_question(self, messages, case_context):
            conversations.append(messages)
            contexts.append(case_context)
            return ModelResult(
                value=ReviewerAssistantAnswer(
                    answer="The portal name and document name differ; inspect registration.txt, page 1.",
                    cited_chunk_ids=[],
                ),
                input_tokens=10,
                output_tokens=8,
            )

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_settings] = lambda: Settings(upload_dir=tmp_path / "uploads", chroma_path=tmp_path / "chroma")
    monkeypatch.setattr("app.routers.ai._get_ai_service", lambda: FakeAssistant())
    monkeypatch.setattr("app.routers.ai.get_chunk_collection", lambda: EmptyCollection())
    try:
        with Session(engine) as db:
            supplier = Supplier(
                name="Portal Name Pvt Ltd", country="India", category="GOODS", subcategory="GOODS-OFF",
                contact_email="review@example.com", tax_reference="DEMO-PAN-1",
                bank_account_number="DEMO-ACCOUNT-1", bank_ifsc="DEMO0123456",
            )
            document = Document(
                supplier=supplier, document_type=DocumentType.REGISTRATION,
                filename="registration.txt", storage_path=str(tmp_path / "registration.txt"),
                content_type="text/plain", file_size=10, page_count=1,
                processing_status=ProcessingStatus.READY, review_status="disputed",
                review_comment="The registered names do not match.",
            )
            db.add_all([supplier, document])
            db.flush()
            db.add(ExtractedField(
                supplier=supplier, document=document, field_name="supplier_name",
                value="Document Name Pvt Ltd", page_number=1, confidence=0.98,
            ))
            db.add(ComplianceResult(
                supplier=supplier, rule_code="BASE-001.R1", status=ComplianceStatus.FAIL,
                message="The registered legal name does not match the portal entry.",
                evidence={"observed": "Document Name Pvt Ltd", "expected": "Portal Name Pvt Ltd"},
            ))
            db.commit()
            supplier_id = supplier.id

        with TestClient(app) as client:
            reviewer = client.post("/api/portal/auth/reviewer-demo").json()
            headers = {"Authorization": f"Bearer {reviewer['token']}"}
            first = client.post(f"/api/suppliers/{supplier_id}/assistant", headers=headers, json={
                "messages": [{"role": "user", "content": "Why are the names different?"}],
            })
            assert first.status_code == 200, first.text
            assert "registration.txt, page 1" in first.json()["answer"]
            assert "Portal-entered values" in contexts[0]
            assert "AI-extracted from registration.txt, page 1" in contexts[0]
            assert "BASE-001.R1" in contexts[0]

            second = client.post(f"/api/suppliers/{supplier_id}/assistant", headers=headers, json={
                "messages": [{"role": "user", "content": "What should I inspect next?"}],
            })
            assert second.status_code == 200, second.text
            assert len(conversations[1]) == 3
            assert conversations[1][0]["content"] == "Why are the names different?"

            history = client.get(f"/api/suppliers/{supplier_id}/assistant/history", headers=headers).json()
            assert [item["role"] for item in history] == ["user", "assistant", "user", "assistant"]
            assert client.delete(f"/api/suppliers/{supplier_id}/assistant/history", headers=headers).status_code == 204
            assert client.get(f"/api/suppliers/{supplier_id}/assistant/history", headers=headers).json() == []
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
