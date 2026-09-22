from datetime import date

from app.models import DocumentType
from app.services.document_policy import BASE_TYPES, extraction_field_names, load_policy
from app.services.policy_evaluator import evaluate_objective_check


def test_only_six_semantic_checks_are_delegated_to_ai() -> None:
    delegated: set[tuple[str, int]] = set()
    for requirement_id, requirement in load_policy().requirements.items():
        document_type = (
            BASE_TYPES[requirement_id]
            if requirement_id in BASE_TYPES
            else DocumentType(requirement_id)
        )
        fields = {name: "Demo value" for name in extraction_field_names(document_type)}
        for check_number in range(1, len(requirement.checks) + 1):
            result = evaluate_objective_check(
                requirement_id,
                check_number,
                fields,
                baseline_name="Demo Supplier",
                portal_name="Demo Supplier",
                portal_tax_reference="DEMO-PAN",
                portal_bank_account="990000000001",
                portal_bank_ifsc="DEMO0001234",
                evaluation_date=date(2026, 9, 22),
            )
            if result is None:
                delegated.add((requirement_id, check_number))

    assert delegated == {
        ("CRED-001", 1),
        ("SITE-001", 1),
        ("SITE-002", 1),
        ("PROD-001", 1),
        ("TRAIN-001", 1),
        ("TRAIN-001", 2),
    }


def test_privacy_threshold_accepts_calendar_days() -> None:
    result = evaluate_objective_check(
        "PRIV-001",
        2,
        {
            "whether_personal_data_is_processed": "Yes",
            "retention_after_service_end": "12 months",
            "deletion_interval": "15 calendar days",
        },
        baseline_name="Brindle Cyber Shield 002 Pvt Ltd",
        portal_name="Brindle Cyber Shield 002 Pvt Ltd",
        portal_tax_reference=None,
        portal_bank_account=None,
        portal_bank_ifsc=None,
        evaluation_date=date(2026, 9, 22),
    )

    assert result is not None
    assert result.result == "matched"
    assert result.reason == "Retention is 12 months and deletion is 15 days, within policy limits."


def test_privacy_threshold_leaves_business_days_for_human_review() -> None:
    result = evaluate_objective_check(
        "PRIV-001",
        2,
        {
            "whether_personal_data_is_processed": "Yes",
            "retention_after_service_end": "12 months",
            "deletion_interval": "15 business days",
        },
        baseline_name="Demo Supplier",
        portal_name="Demo Supplier",
        portal_tax_reference=None,
        portal_bank_account=None,
        portal_bank_ifsc=None,
        evaluation_date=date(2026, 9, 22),
    )

    assert result is not None
    assert result.result == "human_review"
