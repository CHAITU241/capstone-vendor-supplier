"""Deterministic applicability from the frozen synthetic policy v1.1 corpus."""

import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.models import DocumentType, Supplier

POLICY_FILE = Path(__file__).resolve().parents[2] / "policy" / "requirements.json"
BASE_TYPES = {
    "BASE-001": DocumentType.REGISTRATION,
    "BASE-002": DocumentType.TAX,
    "BASE-003": DocumentType.BANK,
}


class Requirement(BaseModel):
    label: str
    why: str
    accepted_evidence: str
    required_fields: str
    checks: list[str] = Field(min_length=2, max_length=2)
    source: str


class Subcategory(BaseModel):
    code: str
    label: str
    definition: str
    examples: str
    boundary: str
    requirements: list[str]
    source: str


class Category(BaseModel):
    code: str
    label: str
    subcategories: list[Subcategory]


class Policy(BaseModel):
    version: str
    status: str
    scope: str
    baseline: list[str]
    requirements: dict[str, Requirement]
    categories: list[Category]


class RequiredDocument(BaseModel):
    document_type: DocumentType
    requirement_id: str = ""  # Existing submitted snapshots predate the policy corpus.
    label: str
    why: str
    accepted_evidence: str = ""
    required_fields: str = ""
    checks: list[str] = Field(default_factory=list)
    source: str = ""


class Checklist(BaseModel):
    version: str
    status: str
    reason: str
    documents: list[RequiredDocument]


@lru_cache(maxsize=1)
def load_policy() -> Policy:
    policy = Policy.model_validate_json(POLICY_FILE.read_text(encoding="utf-8"))
    codes = [item.code for category in policy.categories for item in category.subcategories]
    if len(policy.requirements) != 22 or len(codes) != 25 or len(codes) != len(set(codes)):
        raise ValueError("The synthetic policy must contain 22 IDs and 25 unique subcategories, including Other.")
    if len({category.code for category in policy.categories}) != 9:
        raise ValueError("The synthetic policy must contain eight policy categories plus the controlled Other path.")
    if policy.baseline != ["BASE-001", "BASE-002", "BASE-003"]:
        raise ValueError("The baseline requirements do not match policy v1.1.")
    for category in policy.categories:
        for subcategory in category.subcategories:
            if not subcategory.code.startswith(f"{category.code}-"):
                raise ValueError(f"Subcategory {subcategory.code} has the wrong category.")
            required = policy.baseline + subcategory.requirements
            if len(required) != len(set(required)) or any(code not in policy.requirements for code in required):
                raise ValueError(f"Duplicate or undefined requirement for {subcategory.code}.")
            for code in required:
                if code not in BASE_TYPES:
                    DocumentType(code)  # Every requested item must be uploadable.
    return policy


def category_for(code: str) -> Category | None:
    return next((item for item in load_policy().categories if item.code == code), None)


def subcategory_for(category_code: str, subcategory_code: str) -> Subcategory | None:
    category = category_for(category_code)
    return next((item for item in category.subcategories if item.code == subcategory_code), None) if category else None


def checklist_for(supplier: Supplier) -> Checklist:
    if supplier.submitted_at is not None and supplier.requirements_snapshot:
        return Checklist.model_validate(supplier.requirements_snapshot)
    if supplier.submitted_at is not None and not supplier.requirements_snapshot:
        # Reviewer-created cases before the supplier portal did not store a checklist.
        return Checklist(version="legacy-demo", status="legacy_demo",
                         reason="This case predates policy v1.1 and retains its original three-document checklist.",
                         documents=[RequiredDocument(document_type=kind, label=label, why="Legacy demo evidence")
                                    for kind, label in ((DocumentType.REGISTRATION, "Business registration"),
                                                        (DocumentType.TAX, "Tax registration"),
                                                        (DocumentType.INSURANCE, "Insurance certificate"))])
    policy = load_policy()
    subcategory = subcategory_for(supplier.category or "", supplier.subcategory or "")
    if not subcategory:
        return Checklist(version=policy.version, status="classification_required",
                         reason="Choose your primary service before uploading documents.", documents=[])
    documents = []
    for code in policy.baseline + subcategory.requirements:
        definition = policy.requirements[code]
        if code == "TRANS-001":
            documents.extend((
                RequiredDocument(
                    document_type=DocumentType.TRANS_001,
                    requirement_id=code,
                    label="Cargo and transit insurance certificate",
                    why=definition.why,
                    accepted_evidence="Cargo/transit insurance certificate.",
                    required_fields=(
                        "Supplier legal name; insurer; policy number; cargo cover in INR; "
                        "policy effective and expiry dates."
                    ),
                    checks=definition.checks,
                    source=definition.source,
                ),
                RequiredDocument(
                    document_type=DocumentType.TRANS_001_DECLARATION,
                    requirement_id=code,
                    label="Signed custody-control declaration",
                    why="Establish how goods are tracked and controlled while in the supplier's custody.",
                    accepted_evidence="Signed custody-control declaration.",
                    required_fields=(
                        "Supplier legal name; tracking method; custody owner; loss notice interval; "
                        "declaration date."
                    ),
                    checks=definition.checks,
                    source=definition.source,
                ),
            ))
            continue
        documents.append(RequiredDocument(
            document_type=BASE_TYPES[code] if code in BASE_TYPES else DocumentType(code),
            requirement_id=code, **definition.model_dump(),
        ))
    reason = (
        "Other supplier path: the three baseline items are collected now. Policy and Legal must determine any additional evidence before approval."
        if supplier.category == "OTHER"
        else f"One primary subcategory: {subcategory.code}. Three baseline items plus the additional IDs in {subcategory.source}."
    )
    return Checklist(
        version=policy.version, status=policy.status,
        reason=reason,
        documents=documents,
    )


def required_types_for(supplier: Supplier) -> set[DocumentType]:
    return {item.document_type for item in checklist_for(supplier).documents}


CONDITIONAL_EXTRACTION_FIELDS: dict[str, set[str]] = {
    "BASE-002": {
        "gstin_when_registered",
        "declaration_date_and_signatory_when_not_registered",
    },
}

TRANS_001_FIELDS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.TRANS_001: (
        "supplier_name",
        "insurance_provider",
        "policy_number",
        "cargo_cover_in_inr",
        "policy_effective_and_expiry_dates",
    ),
    DocumentType.TRANS_001_DECLARATION: (
        "supplier_name",
        "tracking_method",
        "custody_owner",
        "loss_notice_interval",
        "declaration_date",
    ),
}


def _field_key(label: str, document_type: DocumentType) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")
    aliases = {
        "legal_name": "supplier_name",
        "supplier_legal_name": "supplier_name",
        "beneficiary_legal_name": "supplier_name",
        "policyholder_legal_name": "supplier_name",
        "pan_tax_reference": "tax_identifier",
        "full_account_number": "bank_account_number",
        "ifsc": "bank_ifsc",
        "insurer": "insurance_provider",
    }
    if document_type in {
        DocumentType.INSURANCE,
        DocumentType.INS_CYB_001,
        DocumentType.INS_PI_001,
    }:
        aliases["expiry_date"] = "insurance_expiry_date"
    return aliases.get(key, key)[:100]


def extraction_field_names(document_type: DocumentType) -> list[str]:
    """Return only fields explicitly required by the applicable policy item."""
    if document_type in TRANS_001_FIELDS:
        return list(TRANS_001_FIELDS[document_type])
    requirement_id = requirement_id_for_document_type(document_type)
    definition = load_policy().requirements.get(requirement_id)
    return list(dict.fromkeys(
        _field_key(label, document_type)
        for label in definition.required_fields.split(";")
        if label.strip()
    )) if definition else []


def requirement_id_for_document_type(document_type: DocumentType) -> str:
    if document_type == DocumentType.TRANS_001_DECLARATION:
        return "TRANS-001"
    return next(
        (code for code, kind in BASE_TYPES.items() if kind == document_type),
        document_type.value,
    )


def required_extraction_field_names(document_type: DocumentType) -> list[str]:
    requirement_id = requirement_id_for_document_type(document_type)
    optional = CONDITIONAL_EXTRACTION_FIELDS.get(requirement_id, set())
    return [name for name in extraction_field_names(document_type) if name not in optional]
