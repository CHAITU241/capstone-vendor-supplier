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


# One policy requirement can require several independently supplied originals.
# Each tuple is: upload type, label, purpose, accepted file, required fields.
COMPOSITE_EVIDENCE_SLOTS: dict[str, tuple[tuple[DocumentType, str, str, str, str], ...]] = {
    "BASE-002": (
        (
            DocumentType.TAX,
            "PAN and tax registration notice",
            "Confirm the supplier's tax identity and GST registration status.",
            "PAN/tax registration notice.",
            "Legal name; PAN/tax reference; GST status (registered or not registered); GSTIN when registered.",
        ),
        (
            DocumentType.BASE_002_DECLARATION,
            "Signed tax-status declaration",
            "Support a supplier whose GST status is not registered.",
            "Signed tax-status declaration required only when GST status is not registered.",
            "Legal name; GST status; declaration date and signatory.",
        ),
    ),
    "SITE-002": (
        (
            DocumentType.SITE_002,
            "Physical guarding authorization",
            "Confirm that the supplier is authorized to provide physical guarding.",
            "Physical guarding authorization.",
            "Supplier legal name; issuer; authorization number; guarding scope; effective and expiry dates.",
        ),
        (
            DocumentType.SITE_002_TRAINING,
            "Guard-training declaration",
            "Confirm that assigned guards are trained for the contracted service.",
            "Signed supplier guard-training declaration.",
            "Supplier legal name; trained-guard attestation; declaration date.",
        ),
    ),
    "FOOD-002": (
        (
            DocumentType.FOOD_002,
            "Food hygiene certificate",
            "Confirm hygiene certification for the service site.",
            "Food hygiene certificate for the service site.",
            "Supplier legal name; site; certificate issuer, number and expiry.",
        ),
        (
            DocumentType.FOOD_002_PLAN,
            "Signed food safety plan",
            "Confirm operational food-safety controls and recent training.",
            "Signed food safety plan.",
            "Supplier legal name; site; allergen controls; temperature controls; food-handler training date; plan review date.",
        ),
    ),
    "TRANS-001": (
        (
            DocumentType.TRANS_001,
            "Cargo and transit insurance certificate",
            "Protect goods in the supplier's custody during transport.",
            "Cargo/transit insurance certificate.",
            "Supplier legal name; insurer; policy number; cargo cover in INR; policy effective and expiry dates.",
        ),
        (
            DocumentType.TRANS_001_DECLARATION,
            "Signed custody-control declaration",
            "Establish how goods are tracked and controlled while in the supplier's custody.",
            "Signed custody-control declaration.",
            "Supplier legal name; tracking method; custody owner; loss notice interval; declaration date.",
        ),
    ),
    "PROD-001": (
        (
            DocumentType.PROD_001,
            "Manufacturer specification or conformity sheet",
            "Confirm the offered equipment model and manufacturer conformity.",
            "Manufacturer specification/conformity sheet.",
            "Supplier legal name; manufacturer; model or SKU; conformity statement.",
        ),
        (
            DocumentType.PROD_001_WARRANTY,
            "Supplier warranty statement",
            "Confirm warranty duration, start point, and support ownership.",
            "Supplier warranty statement.",
            "Supplier legal name; warranty duration; warranty start event; support contact.",
        ),
    ),
    "TRAIN-001": (
        (
            DocumentType.TRAIN_001,
            "Trainer roster",
            "Identify the trainers proposed for the contracted service.",
            "Trainer roster.",
            "Supplier legal name; trainer names; provider contact.",
        ),
        (
            DocumentType.TRAIN_001_OUTLINE,
            "Course outline",
            "Confirm that the proposed course covers the contracted training topics.",
            "Course outline.",
            "Supplier legal name; course topics.",
        ),
        (
            DocumentType.TRAIN_001_CREDENTIAL,
            "Trainer credential or experience record",
            "Confirm topic-relevant trainer qualifications or delivery experience.",
            "Trainer credential or dated experience record.",
            "Supplier legal name; trainer names; credential number/issuer/expiry or dated experience history.",
        ),
    ),
}


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


def _tax_declaration_required(supplier: Supplier) -> bool:
    """Require the conditional declaration only after non-registration is known."""
    if any(
        document.document_type == DocumentType.BASE_002_DECLARATION
        for document in getattr(supplier, "documents", [])
    ):
        return True
    tax_document = next(
        (
            document for document in getattr(supplier, "documents", [])
            if document.document_type == DocumentType.TAX
        ),
        None,
    )
    if tax_document is None:
        return False
    statuses = [
        field.value.casefold().strip()
        for field in getattr(supplier, "extracted_fields", [])
        if field.document_id == tax_document.id
        and field.field_name == "gst_status_registered_or_not_registered"
    ]
    return any(status in {"not registered", "unregistered"} for status in statuses)


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
        if code in COMPOSITE_EVIDENCE_SLOTS:
            slots = COMPOSITE_EVIDENCE_SLOTS[code]
            if code == "BASE-002" and not _tax_declaration_required(supplier):
                slots = slots[:1]
            documents.extend(
                RequiredDocument(
                    document_type=document_type,
                    requirement_id=code,
                    label=label,
                    why=why,
                    accepted_evidence=accepted_evidence,
                    required_fields=required_fields,
                    checks=definition.checks,
                    source=definition.source,
                )
                for document_type, label, why, accepted_evidence, required_fields in slots
            )
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

PHYSICAL_EVIDENCE_FIELDS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.TAX: (
        "supplier_name",
        "tax_identifier",
        "gst_status_registered_or_not_registered",
        "gstin_when_registered",
    ),
    DocumentType.BASE_002_DECLARATION: (
        "supplier_name",
        "gst_status_registered_or_not_registered",
        "declaration_date_and_signatory_when_not_registered",
    ),
    DocumentType.SITE_002: (
        "supplier_name",
        "issuer",
        "authorization_number",
        "guarding_scope",
        "effective_and_expiry_dates",
    ),
    DocumentType.SITE_002_TRAINING: (
        "supplier_name",
        "trained_guard_attestation",
        "declaration_date",
    ),
    DocumentType.FOOD_002: (
        "supplier_name",
        "site",
        "certificate_issuer_number_and_expiry",
    ),
    DocumentType.FOOD_002_PLAN: (
        "supplier_name",
        "site",
        "allergen_controls",
        "temperature_controls",
        "food_handler_training_date",
        "plan_review_date",
    ),
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
    DocumentType.PROD_001: (
        "supplier_name",
        "manufacturer",
        "model_or_sku",
        "conformity_statement",
    ),
    DocumentType.PROD_001_WARRANTY: (
        "supplier_name",
        "warranty_duration",
        "warranty_start_event",
        "support_contact",
    ),
    DocumentType.TRAIN_001: (
        "supplier_name",
        "trainer_names",
        "provider_contact",
    ),
    DocumentType.TRAIN_001_OUTLINE: (
        "supplier_name",
        "course_topics",
    ),
    DocumentType.TRAIN_001_CREDENTIAL: (
        "supplier_name",
        "trainer_names",
        "credential_number_issuer_expiry_or_dated_experience_history",
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
    if document_type in PHYSICAL_EVIDENCE_FIELDS:
        return list(PHYSICAL_EVIDENCE_FIELDS[document_type])
    requirement_id = requirement_id_for_document_type(document_type)
    definition = load_policy().requirements.get(requirement_id)
    return list(dict.fromkeys(
        _field_key(label, document_type)
        for label in definition.required_fields.split(";")
        if label.strip()
    )) if definition else []


def requirement_id_for_document_type(document_type: DocumentType) -> str:
    composite_parents = {
        DocumentType.BASE_002_DECLARATION: "BASE-002",
        DocumentType.SITE_002_TRAINING: "SITE-002",
        DocumentType.FOOD_002_PLAN: "FOOD-002",
        DocumentType.TRANS_001_DECLARATION: "TRANS-001",
        DocumentType.PROD_001_WARRANTY: "PROD-001",
        DocumentType.TRAIN_001_OUTLINE: "TRAIN-001",
        DocumentType.TRAIN_001_CREDENTIAL: "TRAIN-001",
    }
    if document_type in composite_parents:
        return composite_parents[document_type]
    return next(
        (code for code, kind in BASE_TYPES.items() if kind == document_type),
        document_type.value,
    )


def evidence_slot_for_document_type(
    document_type: DocumentType,
) -> tuple[str, str, str] | None:
    """Return slot-specific label, accepted evidence, and fields when split."""
    for slots in COMPOSITE_EVIDENCE_SLOTS.values():
        for slot_type, label, _why, accepted_evidence, required_fields in slots:
            if slot_type == document_type:
                return label, accepted_evidence, required_fields
    return None


def required_extraction_field_names(document_type: DocumentType) -> list[str]:
    requirement_id = requirement_id_for_document_type(document_type)
    optional = CONDITIONAL_EXTRACTION_FIELDS.get(requirement_id, set())
    return [name for name in extraction_field_names(document_type) if name not in optional]
