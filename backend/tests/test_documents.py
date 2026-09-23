from pathlib import Path

import pymupdf
import pytest

from app.config import Settings
from app.services.documents import DocumentExtractionError, extract_document_text


def rendered_text_image(text: str) -> bytes:
    source = pymupdf.open()
    page = source.new_page(width=900, height=300)
    page.insert_text((60, 140), text, fontsize=28, color=(0, 0, 0))
    pixels = page.get_pixmap(dpi=200, alpha=False)
    image = pixels.tobytes("png")
    source.close()
    return image


def image_only_pdf(image: bytes, path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=900, height=300)
    page.insert_image(page.rect, stream=image)
    document.save(path)
    document.close()


def test_extracts_utf8_text_file(tmp_path: Path) -> None:
    document = tmp_path / "supplier.txt"
    document.write_text("Supplier: Acme Ltd", encoding="utf-8")

    result = extract_document_text(document, "text/plain")

    assert result.page_count == 1
    assert "Supplier: Acme Ltd" in result.text
    assert result.text_extraction_method == "native"
    assert result.ocr_pages == ()


def test_rejects_empty_text_file(tmp_path: Path) -> None:
    document = tmp_path / "empty.txt"
    document.write_text("", encoding="utf-8")

    with pytest.raises(DocumentExtractionError, match="empty"):
        extract_document_text(document, "text/plain")


def test_keeps_usable_native_pdf_text_without_ocr(tmp_path: Path) -> None:
    path = tmp_path / "digital.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Supplier registration certificate for Example Office Supply Private Limited")
    document.save(path)
    document.close()

    result = extract_document_text(path, "application/pdf")

    assert result.text_extraction_method == "native"
    assert result.ocr_pages == ()
    assert "Example Office Supply" in result.text


def test_ocrs_an_image_only_pdf_and_preserves_page_number(tmp_path: Path) -> None:
    path = tmp_path / "scanned.pdf"
    image_only_pdf(rendered_text_image("SCANNED SUPPLIER PRIVATE LIMITED"), path)

    result = extract_document_text(path, "application/pdf")

    assert result.text_extraction_method == "ocr"
    assert result.ocr_pages == (1,)
    assert result.ocr_language == "eng"
    assert result.text.startswith("[Page 1]")
    assert "SCANNED SUPPLIER" in result.text.upper()


def test_ocrs_a_direct_png_upload(tmp_path: Path) -> None:
    path = tmp_path / "bank.png"
    path.write_bytes(rendered_text_image("BANK IFSC DEMO001234"))

    result = extract_document_text(path, "image/png")

    assert result.page_count == 1
    assert result.text_extraction_method == "ocr"
    assert result.ocr_pages == (1,)
    assert "BANK IFSC" in result.text.upper()


def test_uses_native_text_and_ocr_only_on_the_scanned_page(tmp_path: Path) -> None:
    path = tmp_path / "mixed.pdf"
    document = pymupdf.open()
    digital = document.new_page(width=900, height=300)
    digital.insert_text(
        (60, 140),
        "DIGITAL REGISTRATION CERTIFICATE FOR EXAMPLE SUPPLIER PRIVATE LIMITED",
        fontsize=18,
    )
    scanned = document.new_page(width=900, height=300)
    scanned.insert_image(scanned.rect, stream=rendered_text_image("SCANNED BANK CONFIRMATION"))
    document.save(path)
    document.close()

    result = extract_document_text(path, "application/pdf")

    assert result.text_extraction_method == "mixed"
    assert result.ocr_pages == (2,)
    assert "[Page 1]" in result.text and "DIGITAL REGISTRATION" in result.text
    assert "[Page 2]" in result.text and "SCANNED BANK" in result.text.upper()


def test_rejects_scanned_pdf_when_ocr_is_disabled(tmp_path: Path) -> None:
    path = tmp_path / "scanned.pdf"
    image_only_pdf(rendered_text_image("SCANNED SUPPLIER PRIVATE LIMITED"), path)

    with pytest.raises(DocumentExtractionError, match="OCR is disabled"):
        extract_document_text(path, "application/pdf", Settings(ocr_enabled=False))
