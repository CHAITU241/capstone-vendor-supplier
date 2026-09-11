import re
from dataclasses import dataclass

import tiktoken


PAGE_PATTERN = re.compile(r"\[Page (\d+)\]\s*", re.I)


@dataclass(frozen=True)
class TextChunk:
    index: int
    page_number: int
    text: str
    token_count: int


def chunk_document(
    text: str,
    model: str,
    chunk_size: int = 500,
    overlap: int = 75,
) -> list[TextChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")

    parts = PAGE_PATTERN.split(text)
    pages = [
        (int(parts[index]), parts[index + 1].strip())
        for index in range(1, len(parts), 2)
        if parts[index + 1].strip()
    ]
    if not pages and text.strip():
        pages = [(1, text.strip())]

    chunks: list[TextChunk] = []
    step = chunk_size - overlap
    for page_number, page_text in pages:
        tokens = encoding.encode(page_text)
        for start in range(0, len(tokens), step):
            token_slice = tokens[start : start + chunk_size]
            if not token_slice:
                continue
            chunk_text = encoding.decode(token_slice).strip()
            if chunk_text:
                chunks.append(
                    TextChunk(
                        index=len(chunks),
                        page_number=page_number,
                        text=chunk_text,
                        token_count=len(token_slice),
                    )
                )
            if start + chunk_size >= len(tokens):
                break
    return chunks
