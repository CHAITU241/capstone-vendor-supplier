"""The portal catalog and checklist must remain aligned with the 12 PDF sources."""

from app.models import DocumentType, Supplier
from app.services.document_policy import checklist_for, load_policy
from app.services.policy_retrieval import policy_context_for


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
