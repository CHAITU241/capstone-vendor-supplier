"""Deterministic evaluation for objective synthetic policy v1.1 checks.

The extraction model may interpret documents, but it must not perform arithmetic,
date-window, exact-match, or required-value decisions.  Returning ``None`` delegates
only genuinely semantic checks to the model-assisted assessment path.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class PolicyAssessment:
    result: str
    reason: str
    evidence_fields: list[str]


def _text(fields: dict[str, str], name: str) -> str | None:
    value = fields.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _yes(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = _norm(value)
    if normalized in {"yes", "true", "affirmed", "attested", "provided"} or normalized.startswith("yes "):
        return True
    if normalized in {"no", "false", "not provided"} or normalized.startswith("no "):
        return False
    return None


def _dates(value: str | None) -> list[date]:
    if not value:
        return []
    candidates = re.findall(
        r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b|"
        r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b",
        value,
    )
    parsed: list[date] = []
    for candidate in candidates or [value.strip()]:
        normalized = " ".join(candidate.replace(",", " ").split())
        for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
            try:
                parsed.append(datetime.strptime(normalized, pattern).date())
                break
            except ValueError:
                continue
    return parsed


def _duration(value: str | None, target_unit: str) -> float | None:
    if not value:
        return None
    normalized = _norm(value)
    if "business day" in normalized:
        return None
    if normalized in {"daily", "every day", "once daily"}:
        number, unit = 1.0, "days"
    else:
        match = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:calendar\s+)?(hours?|hrs?|days?|months?|years?)",
            normalized,
        )
        if not match:
            return None
        number, unit = float(match.group(1)), match.group(2)
    hours = number
    if unit.startswith("day"):
        hours *= 24
    elif unit.startswith("month"):
        hours *= 30 * 24
    elif unit.startswith("year"):
        hours *= 365 * 24
    if target_unit == "hours":
        return hours
    if target_unit == "days":
        return hours / 24
    if target_unit == "months":
        return hours / (30 * 24)
    return None


def _money_inr(value: str | None) -> float | None:
    if not value:
        return None
    normalized = value.casefold().replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if not match:
        return None
    amount = float(match.group(1))
    if "crore" in normalized or re.search(r"\bcr\b", normalized):
        amount *= 10_000_000
    elif "lakh" in normalized or re.search(r"\blac\b", normalized):
        amount *= 100_000
    return amount


def _matched(reason: str, *fields: str) -> PolicyAssessment:
    return PolicyAssessment("matched", reason, list(fields))


def _failed(reason: str, *fields: str) -> PolicyAssessment:
    return PolicyAssessment("not_matched", reason, list(fields))


def _review(reason: str, *fields: str) -> PolicyAssessment:
    return PolicyAssessment("human_review", reason, list(fields))


def _required(fields: dict[str, str], names: list[str]) -> PolicyAssessment | None:
    missing = [name for name in names if not _text(fields, name)]
    return _review(f"Required extracted value(s) are unavailable: {', '.join(missing)}.", *missing) if missing else None


def _date_window(fields: dict[str, str], name: str, today: date, maximum_age: int) -> PolicyAssessment:
    raw = _text(fields, name)
    parsed = _dates(raw)
    if not parsed:
        return _review(f"{name.replace('_', ' ').title()} could not be parsed as a date.", name)
    value = parsed[-1]
    age = (today - value).days
    if age < 0:
        return _failed(f"{name.replace('_', ' ').title()} {value.isoformat()} is after the evaluation date {today.isoformat()}.", name)
    if age > maximum_age:
        return _failed(f"{name.replace('_', ' ').title()} {value.isoformat()} is {age} days old; the limit is {maximum_age} days.", name)
    return _matched(f"{name.replace('_', ' ').title()} {value.isoformat()} is {age} days before the evaluation date, within the {maximum_age}-day limit.", name)


def _name_matches(value: str | None, expected: str | None, label: str, field: str = "supplier_name") -> PolicyAssessment:
    if not value or not expected:
        return _review(f"{label} cannot be compared because one of the values is unavailable.", field)
    if _norm(value) == _norm(expected):
        return _matched(f"{label} matches: {value}.", field)
    return _failed(f"{label} does not match. Observed “{value}”; expected “{expected}”.", field)


def _two_dates_effective(fields: dict[str, str], name: str, today: date, minimum_remaining: int = 30) -> PolicyAssessment:
    parsed = _dates(_text(fields, name))
    if len(parsed) < 2:
        return _review("Effective and expiry dates could not both be parsed.", name)
    effective, expiry = parsed[0], parsed[-1]
    remaining = (expiry - today).days
    if effective > today:
        return _failed(f"Coverage starts {effective.isoformat()}, after the evaluation date {today.isoformat()}.", name)
    if remaining < minimum_remaining:
        return _failed(f"Coverage expires in {remaining} days; at least {minimum_remaining} days must remain.", name)
    return _matched(f"Coverage is effective and expires in {remaining} days, meeting the {minimum_remaining}-day minimum.", name)


def evaluate_objective_check(
    requirement_id: str,
    check_number: int,
    fields: dict[str, str],
    *,
    baseline_name: str | None,
    portal_name: str | None,
    portal_tax_reference: str | None,
    portal_bank_account: str | None,
    portal_bank_ifsc: str | None,
    evaluation_date: date,
) -> PolicyAssessment | None:
    """Return an authoritative objective result, or None for semantic AI assistance."""
    key = (requirement_id, check_number)

    if key == ("BASE-001", 1):
        return _name_matches(_text(fields, "supplier_name"), portal_name, "Registered legal name")
    if key == ("BASE-001", 2):
        missing = _required(fields, ["registration_date", "status"])
        if missing:
            return missing
        dates = _dates(_text(fields, "registration_date"))
        if not dates:
            return _review("Registration date could not be parsed.", "registration_date", "status")
        if dates[-1] > evaluation_date:
            return _failed(f"Registration date {dates[-1].isoformat()} is after the evaluation date.", "registration_date", "status")
        if _norm(_text(fields, "status") or "") != "active":
            return _failed(f"Registration status is {_text(fields, 'status')}; expected Active.", "registration_date", "status")
        return _matched(f"Registration was active and dated {dates[-1].isoformat()}, on or before evaluation.", "registration_date", "status")

    if key == ("BASE-002", 1):
        name = _name_matches(_text(fields, "supplier_name"), baseline_name, "Tax legal name")
        tax = _text(fields, "tax_identifier")
        if name.result != "matched":
            return name
        if not tax or not portal_tax_reference:
            return _review("PAN/tax reference cannot be compared because one value is unavailable.", "supplier_name", "tax_identifier")
        if _norm(tax) != _norm(portal_tax_reference):
            return _failed(f"PAN/tax reference does not match. Observed “{tax}”; expected “{portal_tax_reference}”.", "supplier_name", "tax_identifier")
        return _matched("Tax legal name matches BASE-001 and the PAN/tax reference matches the portal entry.", "supplier_name", "tax_identifier")
    if key == ("BASE-002", 2):
        status = _norm(_text(fields, "gst_status_registered_or_not_registered") or "")
        if status == "registered":
            gstin = _text(fields, "gstin_when_registered")
            return _matched(f"GST status is registered and GSTIN {gstin} is provided.", "gst_status_registered_or_not_registered", "gstin_when_registered") if gstin else _failed("GST status is registered but no GSTIN was extracted.", "gst_status_registered_or_not_registered", "gstin_when_registered")
        if status in {"not registered", "unregistered"}:
            declaration = _text(fields, "declaration_date_and_signatory_when_not_registered")
            dates = _dates(declaration)
            if not declaration or not dates:
                return _review("The not-registered declaration date/signatory could not be verified from extracted data.", "gst_status_registered_or_not_registered", "declaration_date_and_signatory_when_not_registered")
            age = (evaluation_date - dates[-1]).days
            if 0 <= age <= 180:
                return _matched(f"A signed not-registered declaration dated {dates[-1].isoformat()} is within 180 days.", "gst_status_registered_or_not_registered", "declaration_date_and_signatory_when_not_registered")
            return _failed(f"The tax-status declaration is {age} days old; the limit is 180 days.", "gst_status_registered_or_not_registered", "declaration_date_and_signatory_when_not_registered")
        return _review("GST registration status is missing or ambiguous.", "gst_status_registered_or_not_registered")

    if key == ("BASE-003", 1):
        name = _name_matches(_text(fields, "supplier_name"), baseline_name, "Bank beneficiary name")
        if name.result != "matched":
            return name
        observed_account, observed_ifsc = _text(fields, "bank_account_number"), _text(fields, "bank_ifsc")
        if not all((observed_account, observed_ifsc, portal_bank_account, portal_bank_ifsc)):
            return _review("Bank account and IFSC cannot both be compared with the portal values.", "supplier_name", "bank_account_number", "bank_ifsc")
        account_mismatch = observed_account != portal_bank_account
        ifsc_mismatch = _norm(observed_ifsc) != _norm(portal_bank_ifsc)
        if account_mismatch or ifsc_mismatch:
            mismatches = []
            if account_mismatch:
                mismatches.append("bank account number")
            if ifsc_mismatch:
                mismatches.append("IFSC")
            mismatch_label = " and ".join(mismatches)
            return _failed(
                f"The {mismatch_label} does not exactly match the portal payment field"
                f"{'s' if len(mismatches) > 1 else ''}.",
                "supplier_name",
                "bank_account_number",
                "bank_ifsc",
            )
        return _matched("Beneficiary name matches BASE-001 and the account number and IFSC match the portal fields.", "supplier_name", "bank_account_number", "bank_ifsc")
    if key == ("BASE-003", 2):
        return _date_window(fields, "document_date", evaluation_date, 90)

    if key == ("CONF-001", 1):
        name = _name_matches(_text(fields, "supplier_name"), baseline_name, "Confidentiality supplier name")
        if name.result != "matched":
            return name
        signatures = _text(fields, "both_signatures")
        if not signatures:
            return _failed("Both-party signatures were not extracted.", "supplier_name", "both_signatures")
        return _matched("Supplier name matches BASE-001 and both-party signature evidence is present for reviewer verification.", "supplier_name", "both_signatures")
    if key == ("CONF-001", 2):
        return _date_window(fields, "execution_date", evaluation_date, 365)

    if key == ("SEC-001", 1):
        names = ["privileged_account_mfa", "encryption_at_rest", "encryption_in_transit"]
        missing = _required(fields, names)
        if missing:
            return missing
        failed = [name for name in names if _yes(_text(fields, name)) is not True]
        return _failed(f"Required Yes control(s) are not affirmed: {', '.join(failed)}.", *names) if failed else _matched("MFA, encryption at rest, and encryption in transit are all Yes.", *names)
    if key == ("SEC-001", 2):
        interval = _duration(_text(fields, "incident_notice_commitment"), "hours")
        dates = _dates(_text(fields, "signature_and_date"))
        if interval is None or not dates:
            return _review("Incident-notice hours or signed date could not be parsed.", "incident_notice_commitment", "signature_and_date")
        age = (evaluation_date - dates[-1]).days
        if interval > 48:
            return _failed(f"Incident notice is {interval:g} hours; the maximum is 48 hours.", "incident_notice_commitment", "signature_and_date")
        if not 0 <= age <= 180:
            return _failed(f"Signed date is {age} days before evaluation; it must be between 0 and 180 days old.", "incident_notice_commitment", "signature_and_date")
        return _matched(f"Incident notice is {interval:g} hours and the signed date is {age} days old; both limits are met.", "incident_notice_commitment", "signature_and_date")

    if key == ("PRIV-001", 1):
        required = ["supplier_name", "whether_personal_data_is_processed", "purpose", "data_categories", "processing_locations", "subprocessors", "retention_after_service_end", "deletion_interval", "signature_and_date"]
        missing = [name for name in required if not _text(fields, name)]
        if missing:
            return _failed(f"Required privacy response(s) are missing: {', '.join(missing)}.", *required)
        processed = _yes(_text(fields, "whether_personal_data_is_processed"))
        if processed is False:
            invalid = [name for name in ("processing_locations", "retention_after_service_end", "deletion_interval") if _norm(_text(fields, name) or "") != "not applicable"]
            if invalid:
                return _failed(f"No personal data is processed, but conditional field(s) are not marked Not applicable: {', '.join(invalid)}.", *required)
        return _matched("All privacy fields are answered with permitted conditional values.", *required)
    if key == ("PRIV-001", 2):
        processed = _yes(_text(fields, "whether_personal_data_is_processed"))
        if processed is False:
            return _matched("No personal data is processed, so retention and deletion thresholds are not applicable.", "whether_personal_data_is_processed", "retention_after_service_end", "deletion_interval")
        if processed is not True:
            return _review("Whether personal data is processed is ambiguous.", "whether_personal_data_is_processed")
        retention = _duration(_text(fields, "retention_after_service_end"), "months")
        deletion = _duration(_text(fields, "deletion_interval"), "days")
        if retention is None or deletion is None:
            return _review("Retention months or deletion days could not be parsed.", "retention_after_service_end", "deletion_interval")
        if retention > 24 or deletion > 30:
            return _failed(f"Retention is {retention:g} months and deletion is {deletion:g} days; limits are 24 months and 30 days.", "retention_after_service_end", "deletion_interval")
        return _matched(f"Retention is {retention:g} months and deletion is {deletion:g} days, within policy limits.", "retention_after_service_end", "deletion_interval")

    if key == ("CONT-001", 1):
        rto = _duration(_text(fields, "recovery_time_objective_rto"), "hours")
        rpo = _duration(_text(fields, "recovery_point_objective_rpo"), "hours")
        if rto is None or rpo is None:
            return _review("RTO or RPO could not be parsed as hours.", "recovery_time_objective_rto", "recovery_point_objective_rpo")
        if rto > 72 or rpo > 24:
            return _failed(f"RTO is {rto:g} hours and RPO is {rpo:g} hours; limits are 72 and 24 hours.", "recovery_time_objective_rto", "recovery_point_objective_rpo")
        return _matched(f"RTO is {rto:g} hours and RPO is {rpo:g} hours, within policy limits.", "recovery_time_objective_rto", "recovery_point_objective_rpo")
    if key == ("CONT-001", 2):
        exercise = _date_window(fields, "last_exercise_date", evaluation_date, 365)
        review = _date_window(fields, "review_date", evaluation_date, 180)
        if exercise.result == "not_matched" or review.result == "not_matched":
            return _failed(f"{exercise.reason} {review.reason}", "last_exercise_date", "review_date")
        if exercise.result == "human_review" or review.result == "human_review":
            return _review(f"{exercise.reason} {review.reason}", "last_exercise_date", "review_date")
        return _matched(f"{exercise.reason} {review.reason}", "last_exercise_date", "review_date")

    if requirement_id in {"INS-CYB-001", "INS-PI-001"} and check_number == 1:
        amount_field = "cyber_coverage_amount_in_inr" if requirement_id == "INS-CYB-001" else "professional_indemnity_amount_in_inr"
        minimum = 50_000_000 if requirement_id == "INS-CYB-001" else 10_000_000
        name = _name_matches(_text(fields, "supplier_name"), baseline_name, "Policyholder name")
        amount = _money_inr(_text(fields, amount_field))
        if name.result != "matched":
            return name
        if amount is None:
            return _review("Coverage amount could not be parsed.", "supplier_name", amount_field)
        if amount < minimum:
            return _failed(f"Coverage is INR {amount:,.0f}; the minimum is INR {minimum:,.0f}.", "supplier_name", amount_field)
        return _matched(f"Policyholder matches BASE-001 and coverage of INR {amount:,.0f} meets the minimum.", "supplier_name", amount_field)
    if requirement_id in {"INS-CYB-001", "INS-PI-001"} and check_number == 2:
        effective = _dates(_text(fields, "effective_date"))
        expiry = _dates(_text(fields, "insurance_expiry_date"))
        if not effective or not expiry:
            return _review("Policy effective or expiry date could not be parsed.", "effective_date", "insurance_expiry_date")
        remaining = (expiry[-1] - evaluation_date).days
        if effective[-1] > evaluation_date or remaining < 30:
            return _failed(f"Policy effective date is {effective[-1].isoformat()} and expiry has {remaining} days remaining; it must be effective with at least 30 days remaining.", "effective_date", "insurance_expiry_date")
        return _matched(f"Policy is effective and has {remaining} days remaining, meeting the 30-day minimum.", "effective_date", "insurance_expiry_date")

    if key == ("CRED-001", 2):
        issued = _dates(_text(fields, "issue_date"))
        expiry = _dates(_text(fields, "expiry_date"))
        if not issued or not expiry:
            return _review("Credential issue or expiry date could not be parsed.", "issue_date", "expiry_date")
        remaining = (expiry[-1] - evaluation_date).days
        if issued[-1] > evaluation_date or remaining < 30:
            return _failed(f"Credential issue date is {issued[-1].isoformat()} and expiry has {remaining} days remaining; issue must precede evaluation and at least 30 days must remain.", "issue_date", "expiry_date")
        return _matched(f"Credential was issued before evaluation and has {remaining} days remaining.", "issue_date", "expiry_date")

    # The remaining catalogue uses the same objective primitives where fields are explicit.
    if key == ("PEOP-001", 1):
        names = ["worker_records_maintained", "wage_and_contract_compliance_attestation"]
        missing = _required(fields, names)
        if missing:
            return missing
        return _matched("Worker records and wage/contract compliance are both affirmed Yes.", *names) if all(_yes(_text(fields, name)) is True for name in names) else _failed("Both worker-record and wage/contract attestations must be Yes.", *names)
    if key == ("PEOP-001", 2):
        if not _text(fields, "workforce_contact"):
            return _failed("Workforce contact is missing.", "workforce_contact", "signature_and_date")
        signed = _date_window(fields, "signature_and_date", evaluation_date, 180)
        return PolicyAssessment(signed.result, f"Workforce contact is present. {signed.reason}", ["workforce_contact", "signature_and_date"])
    if key == ("PEOP-002", 1):
        names = ["identity_check", "consent_procedure", "background_check"]
        coverage = _duration(_text(fields, "coverage_of_assigned_workers"), "days")
        percent_match = re.search(r"100\s*%", _text(fields, "coverage_of_assigned_workers") or "")
        if any(_yes(_text(fields, name)) is not True for name in names) or not percent_match:
            return _failed("Identity, consent and background checks must be Yes for 100% of assigned workers.", *names, "coverage_of_assigned_workers")
        return _matched("Identity, consent and background checks are Yes for 100% of assigned workers.", *names, "coverage_of_assigned_workers")
    if key == ("PEOP-002", 2):
        timing = _norm(_text(fields, "access_timing") or "")
        if not timing:
            return _review("Access timing was not extracted.", "access_timing")
        return _matched("Checks are committed before access is granted.", "access_timing") if "before" in timing and "access" in timing else _failed(f"Access timing does not clearly require checks before access: {_text(fields, 'access_timing')}.", "access_timing")

    if key in {("SITE-001", 2), ("EVENT-001", 2)}:
        notice_field = "incident_notice_interval"
        review_field = "review_date"
        notice = _duration(_text(fields, notice_field), "hours")
        reviewed = _date_window(fields, review_field, evaluation_date, 180)
        if notice is None:
            return _review("Incident-notice interval could not be parsed.", notice_field, review_field)
        if notice > 24 or reviewed.result == "not_matched":
            return _failed(f"Incident notice is {notice:g} hours; maximum is 24. {reviewed.reason}", notice_field, review_field)
        if reviewed.result == "human_review":
            return _review(reviewed.reason, notice_field, review_field)
        return _matched(f"Incident notice is {notice:g} hours and the review is within 180 days.", notice_field, review_field)
    if key == ("SITE-002", 2):
        authorization = _two_dates_effective(fields, "effective_and_expiry_dates", evaluation_date)
        declaration = _date_window(fields, "declaration_date", evaluation_date, 180)
        if authorization.result == "not_matched" or declaration.result == "not_matched":
            return _failed(f"{authorization.reason} {declaration.reason}", "effective_and_expiry_dates", "declaration_date")
        if authorization.result == "human_review" or declaration.result == "human_review":
            return _review(f"{authorization.reason} {declaration.reason}", "effective_and_expiry_dates", "declaration_date")
        return _matched(f"{authorization.reason} {declaration.reason}", "effective_and_expiry_dates", "declaration_date")
    if key == ("EVENT-001", 1):
        names = ["maximum_planned_attendance", "evacuation_arrangements", "first_aid_lead"]
        missing = _required(fields, names)
        return missing or _matched("Maximum attendance, evacuation arrangements, and a first-aid lead are all provided.", *names)

    if key == ("FOOD-001", 1):
        names = ["source_and_batch_traceability", "storage_method"]
        missing = _required(fields, names)
        return missing or _matched("Source/batch traceability and storage methods are documented.", *names)
    if key == ("FOOD-001", 2):
        contact = _text(fields, "recall_contact")
        notice = _duration(_text(fields, "recall_notice_interval"), "hours")
        if not contact or notice is None:
            return _review("Recall contact or notice interval is unavailable.", "recall_contact", "recall_notice_interval")
        return _matched(f"Recall contact is named and notice is {notice:g} hours.", "recall_contact", "recall_notice_interval") if notice <= 24 else _failed(f"Recall notice is {notice:g} hours; maximum is 24.", "recall_contact", "recall_notice_interval")
    if key == ("FOOD-002", 1):
        certificate = _text(fields, "certificate_issuer_number_and_expiry")
        expiry = _dates(certificate)
        site = _text(fields, "site")
        allergen = _text(fields, "allergen_controls")
        temperature = _text(fields, "temperature_controls")
        if not all((certificate, expiry, site, allergen, temperature)):
            return _review("Certificate expiry, site, allergen controls, or temperature controls are unavailable.", "site", "certificate_issuer_number_and_expiry", "allergen_controls", "temperature_controls")
        remaining = (expiry[-1] - evaluation_date).days
        if remaining < 30:
            return _failed(f"Food certificate has {remaining} days remaining; at least 30 days are required.", "site", "certificate_issuer_number_and_expiry", "allergen_controls", "temperature_controls")
        return _matched(f"Service site and both controls are documented; the certificate has {remaining} days remaining.", "site", "certificate_issuer_number_and_expiry", "allergen_controls", "temperature_controls")
    if key == ("FOOD-002", 2):
        training = _date_window(fields, "food_handler_training_date", evaluation_date, 365)
        review = _date_window(fields, "plan_review_date", evaluation_date, 180)
        if training.result == "not_matched" or review.result == "not_matched":
            return _failed(f"{training.reason} {review.reason}", "food_handler_training_date", "plan_review_date")
        if training.result == "human_review" or review.result == "human_review":
            return _review(f"{training.reason} {review.reason}", "food_handler_training_date", "plan_review_date")
        return _matched(f"{training.reason} {review.reason}", "food_handler_training_date", "plan_review_date")

    if key == ("STORE-001", 1):
        logged = _yes(_text(fields, "access_logging"))
        interval = _duration(_text(fields, "inventory_reconciliation_interval"), "days")
        if logged is None or interval is None:
            return _review("Access logging or reconciliation interval is ambiguous.", "access_logging", "inventory_reconciliation_interval")
        return _matched(f"Access logging is affirmed and reconciliation occurs every {interval:g} days.", "access_logging", "inventory_reconciliation_interval") if logged and interval <= 30 else _failed("Access must be logged and reconciliation must occur at least every 30 days.", "access_logging", "inventory_reconciliation_interval")
    if key == ("STORE-001", 2):
        loss = _duration(_text(fields, "loss_escalation_interval"), "hours")
        owner = _text(fields, "control_owner")
        reviewed = _date_window(fields, "review_date", evaluation_date, 180)
        if loss is None or not owner:
            return _review("Loss-escalation hours or control owner is unavailable.", "loss_escalation_interval", "control_owner", "review_date")
        if loss > 24 or reviewed.result == "not_matched":
            return _failed(f"Loss escalation is {loss:g} hours; maximum is 24. {reviewed.reason}", "loss_escalation_interval", "control_owner", "review_date")
        return PolicyAssessment(reviewed.result, f"Control owner is named, loss escalation is {loss:g} hours. {reviewed.reason}", ["loss_escalation_interval", "control_owner", "review_date"])

    if key == ("TRANS-001", 1):
        cover = _money_inr(_text(fields, "cargo_cover_in_inr"))
        tracking = _text(fields, "tracking_method")
        owner = _text(fields, "custody_owner")
        if cover is None or not tracking or not owner:
            return _review("Cargo cover, tracking method, or custody owner is unavailable.", "cargo_cover_in_inr", "tracking_method", "custody_owner")
        if cover < 5_000_000:
            return _failed(f"Cargo cover is INR {cover:,.0f}; the minimum is INR 5,000,000.", "cargo_cover_in_inr", "tracking_method", "custody_owner")
        return _matched(f"Cargo cover is INR {cover:,.0f}; tracking method and custody owner are identified.", "cargo_cover_in_inr", "tracking_method", "custody_owner")
    if key == ("TRANS-001", 2):
        policy = _two_dates_effective(fields, "policy_effective_and_expiry_dates", evaluation_date)
        notice = _duration(_text(fields, "loss_notice_interval"), "hours")
        declaration = _date_window(fields, "declaration_date", evaluation_date, 180)
        if notice is None:
            return _review("Loss-notice interval could not be parsed.", "policy_effective_and_expiry_dates", "loss_notice_interval", "declaration_date")
        if policy.result == "not_matched" or declaration.result == "not_matched" or notice > 24:
            return _failed(f"{policy.reason} Loss notice is {notice:g} hours; maximum is 24. {declaration.reason}", "policy_effective_and_expiry_dates", "loss_notice_interval", "declaration_date")
        if policy.result == "human_review" or declaration.result == "human_review":
            return _review(f"{policy.reason} {declaration.reason}", "policy_effective_and_expiry_dates", "loss_notice_interval", "declaration_date")
        return _matched(f"{policy.reason} Loss notice is {notice:g} hours. {declaration.reason}", "policy_effective_and_expiry_dates", "loss_notice_interval", "declaration_date")

    if key == ("PROD-001", 2):
        warranty = _duration(_text(fields, "warranty_duration"), "months")
        start = _norm(_text(fields, "warranty_start_event") or "")
        contact = _text(fields, "support_contact")
        if warranty is None or not start or not contact:
            return _review("Warranty duration, start event, or support contact is unavailable.", "warranty_duration", "warranty_start_event", "support_contact")
        if warranty < 12 or "delivery" not in start:
            return _failed(f"Warranty is {warranty:g} months and starts at “{_text(fields, 'warranty_start_event')}”; it must be at least 12 months from delivery.", "warranty_duration", "warranty_start_event", "support_contact")
        return _matched(f"Warranty is {warranty:g} months from delivery and a support contact is named.", "warranty_duration", "warranty_start_event", "support_contact")

    if key == ("PAY-001", 1):
        dual = _yes(_text(fields, "dual_authorization"))
        frequency = _duration(_text(fields, "reconciliation_frequency"), "days")
        if dual is None or frequency is None:
            return _review("Dual authorization or reconciliation frequency is ambiguous.", "dual_authorization", "reconciliation_frequency")
        return _matched("Dual authorization is Yes and reconciliation is at least daily.", "dual_authorization", "reconciliation_frequency") if dual and frequency <= 1 else _failed("Dual authorization must be Yes and reconciliation must occur at least daily.", "dual_authorization", "reconciliation_frequency")
    if key == ("PAY-001", 2):
        contact = _text(fields, "dispute_contact")
        interval = _duration(_text(fields, "dispute_escalation_interval"), "hours")
        if not contact or interval is None:
            return _review("Dispute contact or escalation interval is unavailable.", "dispute_contact", "dispute_escalation_interval")
        return _matched(f"Dispute contact is named and escalation is {interval:g} hours.", "dispute_contact", "dispute_escalation_interval") if interval <= 48 else _failed(f"Dispute escalation is {interval:g} hours; maximum is 48.", "dispute_contact", "dispute_escalation_interval")

    # Composite or semantic checks remain model-assisted and always reviewer-gated.
    return None
