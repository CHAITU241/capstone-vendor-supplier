from dataclasses import dataclass
from pathlib import Path

import pymupdf


class DocumentExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    page_count: int


def extract_document_text(path: Path, content_type: str) -> ExtractedDocument:
    if content_type == "application/pdf":
        try:
            with pymupdf.open(path) as pdf:
                pages = [page.get_text("text").strip() for page in pdf]
        except Exception as exc:
            raise DocumentExtractionError("The PDF could not be read.") from exc

        if not any(pages):
            raise DocumentExtractionError(
                "No selectable text was found. Image-only PDFs are not supported yet."
            )
        page_text = [
            f"[Page {index}]\n{text}" for index, text in enumerate(pages, start=1)
        ]
        return ExtractedDocument(text="\n\n".join(page_text), page_count=len(pages))

    if content_type == "text/plain":
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise DocumentExtractionError("The text file must use UTF-8 encoding.") from exc
        if not text:
            raise DocumentExtractionError("The text file is empty.")
        return ExtractedDocument(text=f"[Page 1]\n{text}", page_count=1)

    raise DocumentExtractionError("Only PDF and plain-text files are supported.")

