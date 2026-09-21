"""The portal catalog and checklist must remain aligned with the 12 PDF sources."""

from app.models import Document, DocumentType, ProcessingStatus, Supplier
from app.services.document_policy import checklist_for, load_policy
from app.services.policy_retrieval import (
    application_answer_for, application_context_for, policy_context_for,
    supplier_facing_answer,
)


def test_all_24_codes_have_exact_baseline_and_mapped_additions():
    catalog = load_policy()
    assert len(catalog.categories) == 8
    assert len(catalog.requirements) == 22
    for category in catalog.categories:
        for subcategory in category.subcategories:
            supplier = Supplier(name="Synthetic Ltd", category=category.code, subcategory=subcategory.code)
            checklist = checklist_for(supplier)
            assert [item.requirement_id for item in checklist.documents] == catalog.baseline + subcategory.requirements
            assert len({item.document_type for item in checklist.documents}) == len(checklist.documents)
            assert all(item.source and len(item.checks) == 2 and item.accepted_evidence for item in checklist.documents)


def test_representative_subcategory_edges():
    goods = checklist_for(Supplier(category="GOODS", subcategory="GOODS-OFF"))
    cyber = checklist_for(Supplier(category="TECH", subcategory="TECH-CYB"))
    payments = checklist_for(Supplier(category="SENS", subcategory="SENS-PAY"))
    assert [item.document_type for item in goods.documents] == [DocumentType.REGISTRATION, DocumentType.TAX, DocumentType.BANK]
    assert cyber.documents[-1].requirement_id == "INS-CYB-001"
    assert {item.requirement_id for item in payments.documents} >= {"CRED-001", "PAY-001", "INS-CYB-001"}
    assert checklist_for(Supplier(category="TECH", subcategory="LOG-WH")).documents == []


def test_policy_assistant_retrieves_actual_source_for_requirement():
    context = policy_context_for("What is INS-CYB-001 cyber liability coverage?")
    assert "INS-CYB-001" in context
    assert "03_Evidence_and_Validation_Standards.pdf" in context or "04_TECH_Category_Policy.pdf" in context


def test_cybersecurity_question_includes_plain_evidence_guidance():
    context = policy_context_for("What evidence does a cybersecurity supplier need?")
    assert "Business registration certificate" in context
    assert "Buyer security questionnaire" in context
    assert "Insurer-issued cyber liability insurance certificate" in context


def test_supplier_answer_recovers_from_model_listing_internal_ids():
    answer = supplier_facing_answer(
        "What evidence does a cybersecurity supplier need?",
        "1. BASE-001 2. BASE-002 3. INS-CYB-001",
    )
    assert "Business registration certificate" in answer
    assert "Buyer security questionnaire" in answer
    assert "Insurer-issued cyber liability insurance certificate" in answer
    assert "BASE-001" not in answer
    assert "INS-CYB-001" not in answer


def test_supplier_answer_replaces_internal_id_in_general_guidance():
    answer = supplier_facing_answer("How do I prove my tax status?", "Upload evidence for BASE-002.")
    assert answer == "Upload evidence for Tax registration or accepted tax status."


def test_application_context_uses_selected_service_and_exact_checklist():
    supplier = Supplier(
        name="Example Cyber Ltd", category="TECH", subcategory="TECH-CYB",
        status="new",
    )
    supplier.documents = [
        Document(
            document_type=DocumentType.REGISTRATION,
            filename="registration.txt", storage_path="uploads/registration.txt",
            content_type="text/plain", file_size=10, page_count=1,
            processing_status=ProcessingStatus.READY, review_status="pending",
        )
    ]

    context = application_context_for(supplier)

    assert "Technology and Digital Services / Cybersecurity" in context
    assert "1 of 8 requested evidence files" in context
    assert "Cyber liability coverage" in context
    assert "Recruitment" not in context
    assert "still a draft" in context
    status_answer = application_answer_for(supplier, "Is my review complete?")
    assert status_answer and "still a draft" in status_answer
    upload_answer = application_answer_for(supplier, "Have I uploaded all the documents correctly?")
    assert upload_answer and "1 of 8" in upload_answer and "reviewer confirms" in upload_answer
    checklist_answer = application_answer_for(supplier, "What documents am I supposed to upload?")
    assert checklist_answer and "Cyber liability coverage" in checklist_answer
    assert "Recruitment" not in checklist_answer
