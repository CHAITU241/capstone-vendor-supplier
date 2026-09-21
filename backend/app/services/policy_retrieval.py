"""Small local policy retrieval context for the OpenRouter compatible assistant."""

import re
from functools import lru_cache
from pathlib import Path

from app.models import AiRunStatus, AiRunType, ProcessingStatus, Supplier, SupplierStatus
from app.services.document_policy import checklist_for, load_policy

SOURCE_DIR = Path(__file__).resolve().parents[2] / "policy" / "source"
STOPWORDS = {"what", "which", "does", "this", "that", "the", "for", "and", "are", "can", "how", "why", "supplier", "policy", "need", "document", "documents", "required", "about"}
INTERNAL_ID = re.compile(r"\b[A-Z]+(?:-[A-Z]+)*-\d{3}\b")
STATUS_QUESTION = re.compile(r"\b(?:review|application)\b.*\b(?:complete|completed|done|status|progress|pending)\b|\bstatus\b.*\b(?:review|application)\b", re.IGNORECASE)
UPLOAD_CHECK_QUESTION = re.compile(r"\b(?:uploaded|upload)\b.*\b(?:all|correct|correctly|complete|missing)\b|\b(?:all|any)\b.*\bdocuments?\b.*\b(?:uploaded|missing)\b", re.IGNORECASE)
CHECKLIST_QUESTION = re.compile(r"\b(?:what|which)\b.*\b(?:documents?|evidence|files?)\b.*\b(?:upload|provide|need|required|supposed)\b|\bdocuments?\b.*\b(?:supposed|required)\b.*\bupload\b", re.IGNORECASE)


def _matching_subcategories(question: str):
    for category in load_policy().categories:
        for subcategory in category.subcategories:
            if subcategory.code in question.upper() or subcategory.label.casefold() in question.casefold():
                yield subcategory


def supplier_facing_answer(question: str, answer: str) -> str:
    """Keep internal IDs out of model replies, even if the model ignores its prompt."""
    if not INTERNAL_ID.search(answer):
        return answer

    matches = list(_matching_subcategories(question))
    if len(matches) == 1:
        policy = load_policy()
        subcategory = matches[0]
        lines = [f"For {subcategory.label.lower()} suppliers, prepare these documents:"]
        for code in policy.baseline + subcategory.requirements:
            requirement = policy.requirements[code]
            lines.append(f"- {requirement.label}: {requirement.accepted_evidence} Include {requirement.required_fields}")
        return "\n".join(lines)

    requirements = load_policy().requirements
    return INTERNAL_ID.sub(
        lambda match: requirements[match.group()].label if match.group() in requirements else "the requested document",
        answer,
    )


@lru_cache(maxsize=1)
def _passages() -> list[tuple[str, str]]:
    passages = []
    for path in sorted(SOURCE_DIR.glob("*.txt")):
        # The source texts are extracted verbatim from the twelve versioned PDFs.
        text = re.sub(r"Synthetic onboarding policy \| Version 1\.1[^\n]*Page \d+", "", path.read_text(encoding="utf-8"))
        for paragraph in re.split(r"\n\s*\n", text.replace("\f", "")):
            cleaned = " ".join(paragraph.split())
            if 40 < len(cleaned) < 1800:
                passages.append((path.name.replace(".txt", ".pdf"), cleaned))
    return passages


def policy_context_for(question: str) -> str:
    policy = load_policy()
    tokens = set(re.findall(r"[a-z0-9]+", question.casefold())) - STOPWORDS
    codes = set(re.findall(r"\b[A-Z]+(?:-[A-Z]+)?-\d{3}\b|\b(?:TECH|PROF|WORK|FAC|FOOD|LOG|GOODS|SENS)-[A-Z]+\b", question.upper()))
    catalog = "; ".join(f"{cat.label} / {sub.label}" for cat in policy.categories for sub in cat.subcategories)
    scored = []
    for source, passage in _passages():
        lower = passage.casefold()
        words = set(re.findall(r"[a-z0-9]+", lower))
        score = len(tokens & words) + 8 * sum(code.casefold() in lower for code in codes)
        if score:
            scored.append((score, source, passage))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = scored[:6]
    context = [f"India-based incorporated suppliers. One primary subcategory. Subcategories: {catalog}."]
    for subcategory in _matching_subcategories(question):
        context.append(f"For {subcategory.label} suppliers, the required evidence is:")
        for code in policy.baseline + subcategory.requirements:
            requirement = policy.requirements[code]
            context.append(f"- {requirement.label}: {requirement.accepted_evidence} Required fields: {requirement.required_fields}")
        context.append(f"Service definition: {subcategory.definition} Boundary: {subcategory.boundary}")
    for _, source, passage in selected:
        context.append(f"[{source}] {passage}")
    return "\n\n".join(context)[:11000]


def _application_facts(supplier: Supplier):
    checklist = checklist_for(supplier)
    documents = {item.document_type: item for item in supplier.documents}
    processing_runs = [run for run in supplier.ai_runs if run.run_type == AiRunType.PROCESSING]
    latest_run = max(processing_runs, key=lambda run: run.created_at) if processing_runs else None
    if supplier.status == SupplierStatus.APPROVED:
        journey_status = "Review is complete: the application was approved."
    elif supplier.status == SupplierStatus.REJECTED:
        journey_status = "Review is complete: the application was rejected. The reviewer decision is authoritative."
    elif supplier.submitted_at is None:
        journey_status = "This application is still a draft and has not been submitted for review."
    elif supplier.status == SupplierStatus.PROCESSING:
        journey_status = "The application was submitted and automated document processing is currently in progress. Human review is not complete."
    elif latest_run and latest_run.status == AiRunStatus.FAILED:
        journey_status = "The application was submitted, but automated document processing did not finish. A reviewer can retry it. Human review is still in progress."
    elif latest_run and latest_run.status == AiRunStatus.SUCCEEDED:
        journey_status = "Automated document processing is complete. Human reviewer verification is still in progress."
    else:
        journey_status = "The application was submitted and is awaiting document processing and human review."
    return checklist, documents, latest_run, journey_status


def application_answer_for(supplier: Supplier, question: str) -> str | None:
    """Answer account-state questions deterministically, without an AI round trip."""
    checklist, documents, _, journey_status = _application_facts(supplier)
    ready = [
        item for item in checklist.documents
        if (document := documents.get(item.document_type))
        and document.processing_status == ProcessingStatus.READY
    ]
    missing = [item for item in checklist.documents if item not in ready]

    if STATUS_QUESTION.search(question):
        return journey_status
    if UPLOAD_CHECK_QUESTION.search(question):
        if missing:
            return (
                f"You have {len(ready)} of {len(checklist.documents)} requested evidence files uploaded and text-readable. "
                f"Still needed: {', '.join(item.label for item in missing)}. "
                "This checks upload completeness only; a reviewer confirms whether each document is correct."
            )
        return (
            f"All {len(checklist.documents)} requested evidence files are uploaded and text-readable. "
            "That confirms completeness, not correctness; the human reviewer confirms whether their contents meet the requirements."
        )
    if CHECKLIST_QUESTION.search(question):
        if not checklist.documents:
            return "Choose your primary service category and subcategory first; the portal will then create your exact document checklist."
        lines = ["For your selected service, upload:"]
        for item in checklist.documents:
            state = "uploaded" if item in ready else "not yet uploaded"
            lines.append(f"- {item.label}: {item.accepted_evidence} ({state})")
        return "\n".join(lines)
    return None


def application_context_for(supplier: Supplier) -> str:
    """Authoritative, non-sensitive context for the signed-in supplier assistant."""
    policy = load_policy()
    category = next((item for item in policy.categories if item.code == supplier.category), None)
    subcategory = next(
        (item for item in (category.subcategories if category else []) if item.code == supplier.subcategory),
        None,
    )
    checklist, documents, _, journey_status = _application_facts(supplier)
    ready_count = sum(
        1 for item in checklist.documents
        if (document := documents.get(item.document_type))
        and document.processing_status == ProcessingStatus.READY
    )
    verified_count = sum(
        1 for item in checklist.documents
        if (document := documents.get(item.document_type))
        and document.review_status == "verified"
    )

    lines = [
        "CURRENT SIGNED-IN APPLICATION (authoritative account context):",
        f"Selected service: {category.label if category else 'Not selected'} / {subcategory.label if subcategory else 'Not selected'}.",
        f"Journey status: {journey_status}",
        f"Checklist completeness: {ready_count} of {len(checklist.documents)} requested evidence files are uploaded and text-readable.",
        f"Human evidence verification: {verified_count} of {len(checklist.documents)} items verified.",
        "An uploaded/readable file is not proof that its contents are correct; only the human reviewer confirms that.",
        "The exact checklist for this selected service is:",
    ]
    for item in checklist.documents:
        document = documents.get(item.document_type)
        upload_state = (
            "uploaded and text-readable"
            if document and document.processing_status == ProcessingStatus.READY
            else "uploaded but unreadable/failed"
            if document else "not uploaded"
        )
        lines.append(
            f"- {item.label}: {item.accepted_evidence} Include {item.required_fields} Current upload state: {upload_state}."
        )
    return "\n".join(lines)
