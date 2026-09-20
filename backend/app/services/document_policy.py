"""Versioned, deterministic demo document checklist; no AI calls are involved."""

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.models import DocumentType, Supplier

POLICY_FILE = Path(__file__).resolve().parents[2] / "policy" / "requirements.json"


class DocumentDefinition(BaseModel):
    label: str
    why: str


class Condition(BaseModel):
    category: str | None = None
    subcategory: str | None = None
    country: str | None = None


class Rule(BaseModel):
    when: Condition
    required: list[DocumentType] = Field(min_length=1)
    reason: str


class Policy(BaseModel):
    version: str
    status: str
    documents: dict[DocumentType, DocumentDefinition]
    default_required: list[DocumentType] = Field(min_length=1)
    default_reason: str
    rules: list[Rule]


class RequiredDocument(BaseModel):
    document_type: DocumentType
    label: str
    why: str


class Checklist(BaseModel):
    version: str
    status: str
    reason: str
    documents: list[RequiredDocument]


@lru_cache(maxsize=1)
def load_policy() -> Policy:
    policy = Policy.model_validate_json(POLICY_FILE.read_text(encoding="utf-8"))
    for required in [policy.default_required, *(rule.required for rule in policy.rules)]:
        if len(required) != len(set(required)) or any(kind not in policy.documents for kind in required):
            raise ValueError("Policy has duplicate or undefined document types.")
    return policy


def _matches(condition: Condition, supplier: Supplier) -> bool:
    return all(
        expected is None or (getattr(supplier, field) or "").casefold().strip() == expected.casefold().strip()
        for field, expected in condition.model_dump().items()
    )


def checklist_for(supplier: Supplier) -> Checklist:
    if supplier.submitted_at is not None and supplier.requirements_snapshot:
        return Checklist.model_validate(supplier.requirements_snapshot)
    policy = load_policy()
    match = next((rule for rule in policy.rules if _matches(rule.when, supplier)), None)
    selected = match.required if match else policy.default_required
    return Checklist(
        version=policy.version,
        status=policy.status,
        reason=match.reason if match else policy.default_reason,
        documents=[RequiredDocument(document_type=kind, **policy.documents[kind].model_dump()) for kind in selected],
    )


def required_types_for(supplier: Supplier) -> set[DocumentType]:
    return {item.document_type for item in checklist_for(supplier).documents}
