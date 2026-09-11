from app.services.redaction import redact_pii, restore_placeholders


def test_redacts_seeded_pii_and_can_restore_model_values() -> None:
    text = (
        "GSTIN 27AAECA0000A1Z5, PAN AAECA0000A, "
        "email priya.nair@example.com, phone +91 90000 12345, "
        "account 000420001234567."
    )

    result = redact_pii(text)

    for sensitive_value in (
        "27AAECA0000A1Z5",
        "AAECA0000A",
        "priya.nair@example.com",
        "+91 90000 12345",
        "000420001234567",
    ):
        assert sensitive_value not in result.text
    assert result.counts == {
        "GSTIN": 1,
        "PAN": 1,
        "EMAIL": 1,
        "PHONE": 1,
        "BANK_ACCOUNT": 1,
    }
    assert restore_placeholders("Contact [EMAIL_1]", result.replacements) == (
        "Contact priya.nair@example.com"
    )


def test_reuses_placeholder_for_repeated_value() -> None:
    result = redact_pii("AAECA0000A and AAECA0000A")

    assert result.text == "[PAN_1] and [PAN_1]"
    assert result.counts == {"PAN": 1}
