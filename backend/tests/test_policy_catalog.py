"""The portal catalog and checklist must remain aligned with the 12 PDF sources."""

import json
import uuid
from collections import Counter
from pathlib import Path

from app.models import Document, DocumentType, ExtractedField, ProcessingStatus, Supplier
from app.services.document_policy import checklist_for, extraction_field_names, load_policy
from app.services.policy_retrieval import (
    application_answer_for, application_context_for, policy_context_for,
    supplier_facing_answer,
)


def test_all_25_codes_have_exact_baseline_and_mapped_additions():
    catalog = load_policy()
    assert len(catalog.categories) == 9
    assert len(catalog.requirements) == 22
    for category in catalog.categories:
        for subcategory in category.subcategories:
            supplier = Supplier(name="Synthetic Ltd", category=category.code, subcategory=subcategory.code)
            checklist = checklist_for(supplier)
            assert list(dict.fromkeys(item.requirement_id for item in checklist.documents)) == catalog.baseline + subcategory.requirements
            assert len({item.document_type for item in checklist.documents}) == len(checklist.documents)
            assert all(item.source and len(item.checks) == 2 and item.accepted_evidence for item in checklist.documents)


def test_representative_subcategory_edges():
    goods = checklist_for(Supplier(category="GOODS", subcategory="GOODS-OFF"))
    cyber = checklist_for(Supplier(category="TECH", subcategory="TECH-CYB"))
    payments = checklist_for(Supplier(category="SENS", subcategory="SENS-PAY"))
    courier = checklist_for(Supplier(category="LOG", subcategory="LOG-COU"))
    security = checklist_for(Supplier(category="FAC", subcategory="FAC-SEC"))
    catering = checklist_for(Supplier(category="FOOD", subcategory="FOOD-CAT"))
    training = checklist_for(Supplier(category="WORK", subcategory="WORK-LND"))
    equipment = checklist_for(Supplier(category="GOODS", subcategory="GOODS-ITE"))
    other = checklist_for(Supplier(category="OTHER", subcategory="OTHER-GEN"))
    assert [item.document_type for item in goods.documents] == [DocumentType.REGISTRATION, DocumentType.TAX, DocumentType.BANK]
    assert cyber.documents[-1].requirement_id == "INS-CYB-001"
    assert {item.requirement_id for item in payments.documents} >= {"CRED-001", "PAY-001", "INS-CYB-001"}
    assert [item.document_type for item in courier.documents] == [
        DocumentType.REGISTRATION,
        DocumentType.TAX,
        DocumentType.BANK,
        DocumentType.TRANS_001,
        DocumentType.TRANS_001_DECLARATION,
    ]
    assert [item.requirement_id for item in courier.documents].count("TRANS-001") == 2
    assert [item.requirement_id for item in security.documents].count("SITE-002") == 2
    assert [item.requirement_id for item in catering.documents].count("FOOD-002") == 2
    assert [item.requirement_id for item in training.documents].count("TRAIN-001") == 3
    assert [item.requirement_id for item in equipment.documents].count("PROD-001") == 2
    assert [item.document_type for item in other.documents] == [DocumentType.REGISTRATION, DocumentType.TAX, DocumentType.BANK]
    assert "Policy and Legal" in other.reason
    assert checklist_for(Supplier(category="TECH", subcategory="LOG-WH")).documents == []


def test_transport_physical_files_have_distinct_extraction_fields():
    assert extraction_field_names(DocumentType.TRANS_001) == [
        "supplier_name",
        "insurance_provider",
        "policy_number",
        "cargo_cover_in_inr",
        "policy_effective_and_expiry_dates",
    ]
    assert extraction_field_names(DocumentType.TRANS_001_DECLARATION) == [
        "supplier_name",
        "tracking_method",
        "custody_owner",
        "loss_notice_interval",
        "declaration_date",
    ]


def test_not_registered_tax_status_adds_the_conditional_declaration_slot():
    supplier = Supplier(id=uuid.uuid4(), category="WORK", subcategory="WORK-REC")
    tax_document = Document(
        id=uuid.uuid4(),
        supplier_id=supplier.id,
        document_type=DocumentType.TAX,
        filename="tax.pdf",
        storage_path="uploads/tax.pdf",
        content_type="application/pdf",
        file_size=10,
        page_count=1,
        processing_status=ProcessingStatus.READY,
    )
    supplier.documents = [tax_document]
    status_field = ExtractedField(
        id=uuid.uuid4(),
        supplier_id=supplier.id,
        document_id=tax_document.id,
        field_name="gst_status_registered_or_not_registered",
        value="registered",
        page_number=1,
        confidence=.99,
        needs_review=False,
        review_status="pending",
    )
    supplier.extracted_fields = [status_field]

    assert [
        item.document_type for item in checklist_for(supplier).documents
    ].count(DocumentType.BASE_002_DECLARATION) == 0

    status_field.value = "not registered"

    checklist = checklist_for(supplier)

    assert [item.requirement_id for item in checklist.documents].count("BASE-002") == 2
    assert any(
        item.document_type == DocumentType.BASE_002_DECLARATION
        for item in checklist.documents
    )


def test_each_composite_upload_extracts_only_its_own_fields():
    expected = {
        DocumentType.BASE_002_DECLARATION: {
            "supplier_name", "gst_status_registered_or_not_registered",
            "declaration_date_and_signatory_when_not_registered",
        },
        DocumentType.SITE_002_TRAINING: {
            "supplier_name", "trained_guard_attestation", "declaration_date",
        },
        DocumentType.FOOD_002_PLAN: {
            "supplier_name", "site", "allergen_controls", "temperature_controls",
            "food_handler_training_date", "plan_review_date",
        },
        DocumentType.PROD_001_WARRANTY: {
            "supplier_name", "warranty_duration", "warranty_start_event", "support_contact",
        },
        DocumentType.TRAIN_001_OUTLINE: {"supplier_name", "course_topics"},
        DocumentType.TRAIN_001_CREDENTIAL: {
            "supplier_name", "trainer_names",
            "credential_number_issuer_expiry_or_dated_experience_history",
        },
    }
    assert {
        document_type: set(extraction_field_names(document_type))
        for document_type in expected
    } == expected


def test_packet_manifests_have_one_upload_slot_per_physical_file():
    packet_root = Path(__file__).resolve().parents[2] / "Dummy_Supplier_Packets"
    checked = 0
    mismatches = []
    for packet in sorted(packet_root.glob("SUP-*")):
        record_path = packet / "v01" / "portal_record.json"
        manifest_path = packet / "v01" / "submission_manifest.json"
        if not record_path.exists() or not manifest_path.exists():
            continue
        checked += 1
        record = json.loads(record_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        code = record["primary_code"]
        supplier = Supplier(
            id=uuid.uuid4(), category=code.split("-", 1)[0], subcategory=code,
        )
        if record.get("portal_gst_status", "").casefold() in {
            "not registered", "unregistered",
        }:
            tax_document = Document(
                id=uuid.uuid4(), supplier_id=supplier.id,
                document_type=DocumentType.TAX, filename="tax.pdf",
                storage_path="uploads/tax.pdf", content_type="application/pdf",
                file_size=1, page_count=1, processing_status=ProcessingStatus.READY,
            )
            supplier.documents = [tax_document]
            supplier.extracted_fields = [ExtractedField(
                id=uuid.uuid4(), supplier_id=supplier.id,
                document_id=tax_document.id,
                field_name="gst_status_registered_or_not_registered",
                value=record["portal_gst_status"], page_number=1,
                confidence=.99, needs_review=False, review_status="pending",
            )]
        portal_slots = Counter(
            item.requirement_id for item in checklist_for(supplier).documents
        )
        packet_files = Counter(
            item["requirement_id"] for item in manifest["uploaded_documents"]
        )
        if portal_slots != packet_files:
            mismatches.append((packet.name, packet_files, portal_slots))

    assert checked == 20
    assert mismatches == []


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
