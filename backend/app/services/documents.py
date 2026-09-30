from dataclasses import dataclass
from pathlib import Path
import re

import pymupdf

from app.config import Settings
from app.services.tracing import get_langfuse_tracer


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
    ocr_quality_score: int | None = None
    ocr_quality_status: str | None = None
    ocr_quality_details: tuple[dict, ...] = ()


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


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def _ocr_visual_quality(page: pymupdf.Page, recognized_text: str, page_number: int) -> dict:
    """Estimate OCR suitability from pixels and recognised-text yield.

    This is deliberately labelled extraction reliability, not document
    authenticity. It detects blur, weak contrast, poor illumination and
    undersized source images without making a fraud judgment.
    """
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(0.5, 0.5),
        colorspace=pymupdf.csGRAY,
        alpha=False,
    )
    samples = pixmap.samples
    sample_step = max(len(samples) // 50000, 1)
    sampled = samples[::sample_step] or bytes([255])
    mean = sum(sampled) / len(sampled)
    variance = sum((value - mean) ** 2 for value in sampled) / len(sampled)
    contrast = variance ** 0.5

    horizontal_step = max(pixmap.width // 250, 1)
    vertical_step = max(pixmap.height // 250, 1)
    differences: list[int] = []
    stride = pixmap.stride
    for y in range(0, pixmap.height, vertical_step):
        row = y * stride
        for x in range(horizontal_step, pixmap.width, horizontal_step):
            current = samples[row + x]
            previous = samples[row + x - horizontal_step]
            differences.append(abs(current - previous))
    edge_strength = sum(differences) / max(len(differences), 1)

    source_dimensions = [
        (int(image[2]), int(image[3]))
        for image in page.get_images(full=True)
        if len(image) > 3 and int(image[2]) > 0 and int(image[3]) > 0
    ]
    source_short_edge = max(
        (min(width, height) for width, height in source_dimensions),
        default=min(pixmap.width * 2, pixmap.height * 2),
    )
    alphanumeric_chars = sum(character.isalnum() for character in recognized_text)
    word_count = len(re.findall(r"\b\w+\b", recognized_text, flags=re.UNICODE))

    resolution_score = _clamp_score((source_short_edge - 250) / 750 * 100)
    contrast_score = _clamp_score((contrast - 8) / 32 * 100)
    sharpness_score = _clamp_score((edge_strength - 1.5) / 10.5 * 100)
    text_yield_score = _clamp_score(
        0.65 * min(alphanumeric_chars / 180, 1) * 100
        + 0.35 * min(word_count / 35, 1) * 100
    )
    if mean < 35:
        illumination_score = _clamp_score(mean / 35 * 100)
    elif mean > 225:
        illumination_score = _clamp_score((255 - mean) / 30 * 100)
    else:
        illumination_score = 100.0
    score = round(
        0.25 * resolution_score
        + 0.25 * contrast_score
        + 0.25 * sharpness_score
        + 0.20 * text_yield_score
        + 0.05 * illumination_score
    )
    return {
        "page_number": page_number,
        "visual_score": int(_clamp_score(score)),
        "source_short_edge_px": source_short_edge,
        "contrast": round(contrast, 2),
        "edge_strength": round(edge_strength, 2),
        "mean_brightness": round(mean, 2),
        "recognised_alphanumeric_chars": alphanumeric_chars,
        "recognised_words": word_count,
    }


def _quality_status(score: int, settings: Settings) -> str:
    if score < settings.ocr_quality_reject_threshold:
        return "poor"
    if score < settings.ocr_quality_review_threshold:
        return "review"
    return "good"


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
        quality_details: list[dict] = []
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
                    quality_details.append(_ocr_visual_quality(page, text, index))
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
        visual_score = (
            round(sum(item["visual_score"] for item in quality_details) / len(quality_details))
            if quality_details else None
        )
        return ExtractedDocument(
            text="\n\n".join(pages),
            page_count=document.page_count,
            text_extraction_method=method,
            ocr_pages=tuple(ocr_pages),
            ocr_language=settings.ocr_language if ocr_pages else None,
            ocr_warnings=tuple(warnings),
            ocr_quality_score=visual_score,
            ocr_quality_status=_quality_status(visual_score, settings) if visual_score is not None else None,
            ocr_quality_details=tuple(quality_details),
        )


def _extract_document_text(path: Path, content_type: str, settings: Settings) -> ExtractedDocument:
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


def extract_document_text(path: Path, content_type: str, settings: Settings | None = None) -> ExtractedDocument:
    settings = settings or Settings()
    tracer = get_langfuse_tracer()
    with tracer.trace(
        name="document.text_extraction",
        input_data={
            "content_type": content_type,
            "file_extension": path.suffix.lower() or "unknown",
        },
        metadata={
            "feature": "text_extraction",
            "content_type": content_type,
            "file_extension": path.suffix.lower() or "unknown",
            "ocr_enabled": settings.ocr_enabled,
            "ocr_language": settings.ocr_language,
        },
        tags=["document", "ocr"],
    ) as trace:
        result = _extract_document_text(path, content_type, settings)
        trace.update(output={
            "method": result.text_extraction_method,
            "page_count": result.page_count,
            "ocr_page_count": len(result.ocr_pages),
            "warning_count": len(result.ocr_warnings),
            "text_chars": len(result.text),
            "ocr_quality_score": result.ocr_quality_score,
            "ocr_quality_status": result.ocr_quality_status,
        })
        trace.score_trace(name="text_extraction_success", value=1)
        return result
