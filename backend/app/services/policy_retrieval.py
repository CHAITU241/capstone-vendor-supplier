"""Small local policy retrieval context for the OpenRouter compatible assistant."""

import re
from functools import lru_cache
from pathlib import Path

from app.services.document_policy import load_policy

SOURCE_DIR = Path(__file__).resolve().parents[2] / "policy" / "source"
STOPWORDS = {"what", "which", "does", "this", "that", "the", "for", "and", "are", "can", "how", "why", "supplier", "policy", "need", "document", "documents", "required", "about"}
INTERNAL_ID = re.compile(r"\b[A-Z]+(?:-[A-Z]+)*-\d{3}\b")


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
