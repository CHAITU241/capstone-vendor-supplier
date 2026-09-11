from pathlib import Path

import pytest

from app.services.documents import DocumentExtractionError, extract_document_text


def test_extracts_utf8_text_file(tmp_path: Path) -> None:
    document = tmp_path / "supplier.txt"
    document.write_text("Supplier: Acme Ltd", encoding="utf-8")

    result = extract_document_text(document, "text/plain")

    assert result.page_count == 1
    assert "Supplier: Acme Ltd" in result.text


def test_rejects_empty_text_file(tmp_path: Path) -> None:
    document = tmp_path / "empty.txt"
    document.write_text("", encoding="utf-8")

    with pytest.raises(DocumentExtractionError, match="empty"):
        extract_document_text(document, "text/plain")

