import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionResult:
    text: str
    replacements: dict[str, str]
    counts: dict[str, int]


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "GSTIN",
        re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b", re.I),
    ),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.I)),
    ("CIN", re.compile(r"\b[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b", re.I)),
    ("EMAIL", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("PHONE", re.compile(r"(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b")),
    ("BANK_ACCOUNT", re.compile(r"\b\d{12,18}\b")),
)


def redact_pii(text: str) -> RedactionResult:
    redacted = text
    replacements: dict[str, str] = {}
    counts: dict[str, int] = {}

    for category, pattern in PATTERNS:
        value_to_placeholder: dict[str, str] = {}

        def replace(match: re.Match[str]) -> str:
            value = match.group(0)
            normalized = value.upper() if category in {"GSTIN", "PAN", "CIN"} else value
            if normalized not in value_to_placeholder:
                index = len(value_to_placeholder) + 1
                placeholder = f"[{category}_{index}]"
                value_to_placeholder[normalized] = placeholder
                replacements[placeholder] = value
            return value_to_placeholder[normalized]

        redacted = pattern.sub(replace, redacted)
        if value_to_placeholder:
            counts[category] = len(value_to_placeholder)

    return RedactionResult(text=redacted, replacements=replacements, counts=counts)


def restore_placeholders(value: str, replacements: dict[str, str]) -> str:
    restored = value
    for placeholder, original in replacements.items():
        restored = restored.replace(placeholder, original)
    return restored
