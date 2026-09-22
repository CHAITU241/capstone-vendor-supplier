import uuid

from app.models import DocumentType
from app.services.document_policy import extraction_field_names
from app.services.openai_service import DocumentExtraction
from app.services.processing import (
    FieldCandidate,
    comparison_key,
    normalize_extracted_value,
    select_canonical_fields,
)


def candidate(
    document_type: DocumentType,
    field_name: str,
    value: str,
    confidence: float = 0.9,
    needs_review: bool = False,
) -> FieldCandidate:
    return FieldCandidate(
        document_id=uuid.uuid4(),
        document_type=document_type,
        field_name=field_name,
        value=value,
        page_number=1,
        confidence=confidence,
        needs_review=needs_review,
    )


def test_normalizes_null_like_values_and_restores_placeholders() -> None:
    replacements = {"[EMAIL_1]": "reviewer@example.com"}

    assert normalize_extracted_value(None, replacements) is None
    assert normalize_extracted_value(' "null" ', replacements) is None
    assert normalize_extracted_value("N/A", replacements) is None
    assert normalize_extracted_value("[EMAIL_1]", replacements) == "reviewer@example.com"


def test_collapses_exact_duplicates_to_preferred_source() -> None:
    registration = candidate(
        DocumentType.REGISTRATION,
        "supplier_name",
        "Asteron Industrial Components Private Limited",
    )
    tax = candidate(
        DocumentType.TAX,
        "supplier_name",
        "Asteron Industrial Components Private Limited",
        confidence=0.98,
    )

    selected, conflicts = select_canonical_fields([tax, registration])

    assert selected == [registration]
    assert conflicts == []


def test_prefers_authoritative_source_and_flags_conflicting_values() -> None:
    registration = candidate(
        DocumentType.REGISTRATION,
        "tax_identifier",
        "27AAAAA0000A1Z1",
        confidence=0.99,
    )
    tax = candidate(
        DocumentType.TAX,
        "tax_identifier",
        "27BBBBB0000B1Z2",
        confidence=0.9,
    )

    selected, conflicts = select_canonical_fields([registration, tax])

    assert selected[0].document_id == tax.document_id
    assert selected[0].needs_review is True
    assert conflicts == ["tax_identifier"]


def test_does_not_treat_role_specific_names_as_contact_conflicts() -> None:
    registration = candidate(
        DocumentType.REGISTRATION,
        "contact_name",
        "Priya Nair",
    )
    tax_signatory = candidate(
        DocumentType.TAX,
        "contact_name",
        "Arjun Mehta",
    )
    insurance_representative = candidate(
        DocumentType.INSURANCE,
        "contact_name",
        "Maya Deshpande",
    )

    selected, conflicts = select_canonical_fields(
        [registration, tax_signatory, insurance_representative]
    )

    assert selected[0].value == "Priya Nair"
    assert selected[0].needs_review is False
    assert conflicts == []


def test_ignores_name_punctuation_when_checking_conflicts() -> None:
    registration = candidate(
        DocumentType.REGISTRATION,
        "supplier_name",
        "Eastbridge Logistics and Warehousing Private Limited.",
    )
    tax = candidate(
        DocumentType.TAX,
        "supplier_name",
        "Eastbridge Logistics and Warehousing Private Limited",
    )

    selected, conflicts = select_canonical_fields([registration, tax])

    assert comparison_key("supplier_name", registration.value) == comparison_key(
        "supplier_name", tax.value
    )
    assert selected[0].needs_review is False
    assert conflicts == []


def test_confidentiality_extraction_uses_requirement_specific_fields() -> None:
    fields = extraction_field_names(DocumentType.CONF_001)

    assert fields == [
        "supplier_name",
        "buyer_name",
        "signatory_names",
        "both_signatures",
        "execution_date",
    ]


def test_business_registration_does_not_invent_erp_fields_as_policy_fields() -> None:
    fields = extraction_field_names(DocumentType.REGISTRATION)

    assert fields == [
        "supplier_name",
        "registration_number",
        "issuing_registry",
        "registration_date",
        "status",
    ]
    assert "address" not in fields
    assert "contact_email" not in fields


def test_extraction_schema_rejects_runaway_field_values() -> None:
    payload = {
        "classified_document_type": "CONF-001",
        "fields": [{
            "field_name": "buyer_name",
            "value": "x" * 301,
            "page_number": 1,
            "confidence": 0.9,
        }],
    }

    try:
        DocumentExtraction.model_validate(payload)
    except ValueError:
        pass
    else:
        raise AssertionError("The structured extraction schema accepted a runaway value.")
