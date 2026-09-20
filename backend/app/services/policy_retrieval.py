"""Small local policy retrieval context for the OpenRouter compatible assistant."""

import re
from functools import lru_cache
from pathlib import Path

from app.services.document_policy import load_policy

SOURCE_DIR = Path(__file__).resolve().parents[2] / "policy" / "source"
STOPWORDS = {"what", "which", "does", "this", "that", "the", "for", "and", "are", "can", "how", "why", "supplier", "policy", "need", "document", "documents", "required", "about"}


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
    catalog = "; ".join(f"{sub.code}: {sub.label}" for cat in policy.categories for sub in cat.subcategories)
    scored = []
    for source, passage in _passages():
        lower = passage.casefold()
        words = set(re.findall(r"[a-z0-9]+", lower))
        score = len(tokens & words) + 8 * sum(code.casefold() in lower for code in codes)
        if score:
            scored.append((score, source, passage))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = scored[:6]
    context = [f"Synthetic buyer policy v1.1. India-based incorporated entities only. One primary code. Subcategories: {catalog}."]
    for category in policy.categories:
        for subcategory in category.subcategories:
            if subcategory.code in codes or subcategory.label.casefold() in question.casefold():
                required = policy.baseline + subcategory.requirements
                context.append(f"[{subcategory.source}] {subcategory.code} requires exactly: {', '.join(required)}. {subcategory.definition} Boundary: {subcategory.boundary}")
    for _, source, passage in selected:
        context.append(f"[{source}] {passage}")
    return "\n\n".join(context)[:11000]
