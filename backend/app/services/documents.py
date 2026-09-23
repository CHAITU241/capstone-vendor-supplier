from dataclasses import dataclass
from pathlib import Path
import re

import pymupdf

from app.config import Settings


class DocumentExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    page_count: int
    text_extraction_method: str
    ocr_pages: tuple[int, ...] = ()
    ocr_language: str | None = None
    ocr_warnings: tuple[str, ...] = ()


def _native_text_is_usable(text: str, settings: Settings) -> bool:
    alphanumeric_count = sum(character.isalnum() for character in text)
    word_count = len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))
    return (
        alphanumeric_count >= settings.ocr_min_native_alphanumeric_chars
        and word_count >= settings.ocr_min_native_words
    )


def _large_image_coverage(page: pymupdf.Page, threshold: float) -> bool:
    page_area = max(page.rect.width * page.rect.height, 1)
    image_area = 0.0
    seen_rectangles: set[tuple[float, float, float, float]] = set()
    try:
        for image in page.get_images(full=True):
            for rectangle in page.get_image_rects(image[0]):
                clipped = rectangle & page.rect
                coordinates = tuple(round(value, 2) for value in (clipped.x0, clipped.y0, clipped.x1, clipped.y1))
                if clipped.is_empty or coordinates in seen_rectangles:
                    continue
                seen_rectangles.add(coordinates)
                image_area += clipped.width * clipped.height
    except Exception:
        return False
    return min(image_area / page_area, 1.0) >= threshold


def _ocr_page(page: pymupdf.Page, settings: Settings, *, full: bool) -> str:
    try:
        text_page = page.get_textpage_ocr(
            language=settings.ocr_language,
            dpi=settings.ocr_dpi,
            full=full,
        )
        return page.get_text("text", textpage=text_page).strip()
    except Exception as exc:
        raise DocumentExtractionError(
            "OCR could not read the scanned page. Confirm that Tesseract and the "
            f"'{settings.ocr_language}' language data are installed."
        ) from exc


def _extract_visual_document(path: Path, settings: Settings) -> ExtractedDocument:
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise DocumentExtractionError("The document could not be read.") from exc

    with document:
        pages: list[str] = []
        ocr_pages: list[int] = []
        warnings: list[str] = []
        for index, page in enumerate(document, start=1):
            native_text = page.get_text("text").strip()
            native_usable = _native_text_is_usable(native_text, settings)
            image_dominant = _large_image_coverage(page, settings.ocr_image_coverage_threshold)
            should_ocr = not native_usable or image_dominant
            text = native_text
            if should_ocr:
                if not settings.ocr_enabled:
                    if not native_usable:
                        warnings.append(f"Page {index}: selectable text was insufficient and OCR is disabled.")
                        text = ""
                else:
                    if len(ocr_pages) >= settings.ocr_max_pages:
                        raise DocumentExtractionError(
                            f"The document requires OCR on more than {settings.ocr_max_pages} pages. "
                            "Split it into a smaller evidence file."
                        )
                    text = _ocr_page(page, settings, full=not native_usable)
                    ocr_pages.append(index)
                    if not text:
                        warnings.append(f"Page {index}: OCR did not recognise any text.")
            pages.append(f"[Page {index}]\n{text}")

        if not any(page.partition("\n")[2].strip() for page in pages):
            if settings.ocr_enabled:
                raise DocumentExtractionError("No readable text was found after OCR.")
            raise DocumentExtractionError("No selectable text was found and OCR is disabled.")

        if ocr_pages and len(ocr_pages) == document.page_count:
            method = "ocr"
        elif ocr_pages:
            method = "mixed"
        else:
            method = "native"
        return ExtractedDocument(
            text="\n\n".join(pages),
            page_count=document.page_count,
            text_extraction_method=method,
            ocr_pages=tuple(ocr_pages),
            ocr_language=settings.ocr_language if ocr_pages else None,
            ocr_warnings=tuple(warnings),
        )


def extract_document_text(path: Path, content_type: str, settings: Settings | None = None) -> ExtractedDocument:
    settings = settings or Settings()
    if content_type in {"application/pdf", "image/jpeg", "image/png"}:
        try:
            return _extract_visual_document(path, settings)
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError("The document could not be read.") from exc

    if content_type == "text/plain":
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise DocumentExtractionError("The text file must use UTF-8 encoding.") from exc
        if not text:
            raise DocumentExtractionError("The text file is empty.")
        return ExtractedDocument(
            text=f"[Page 1]\n{text}", page_count=1,
            text_extraction_method="native",
        )

    raise DocumentExtractionError("Only PDF, PNG, JPEG and plain-text files are supported.")
