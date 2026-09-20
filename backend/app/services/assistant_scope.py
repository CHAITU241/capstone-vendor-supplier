"""Conservative scope gate for the public supplier onboarding guide."""

import re


ONBOARDING_TERMS = re.compile(
    r"\b(?:supplier|vendor|onboard\w*|applicat\w*|register\w*|tax|gst\w*|pan|bank|ifsc|"
    r"evidence|document\w*|upload\w*|submit\w*|review\w*|reject\w*|approv\w*|"
    r"requirement\w*|checklist|categor\w*|subcategor\w*|insur\w*|privacy|"
    r"secur\w*|cyber\w*|confidential\w*|continuity|contract\w*|"
    r"certificate\w*|questionnaire|portal|account|sign.?in|login|password|"
    r"payment\w*|procure\w*|prepare|service provider)\b",
    re.IGNORECASE,
)
OFF_TOPIC_TERMS = re.compile(
    r"\b(?:president|prime minister|weather|cricket|football|movie|"
    r"recipe|stock price|capital of|news headline|tell me a joke)\b",
    re.IGNORECASE,
)


def is_onboarding_question(question: str, previous_user_questions: list[str]) -> bool:
    """Require an onboarding topic; permit short follow-ups to an in-scope question."""
    if OFF_TOPIC_TERMS.search(question):
        return False
    if ONBOARDING_TERMS.search(question):
        return True
    if len(question.split()) > 8:
        return False
    for previous in reversed(previous_user_questions[-4:]):
        if OFF_TOPIC_TERMS.search(previous):
            return False
        if ONBOARDING_TERMS.search(previous):
            return True
    return False
