from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    text: str
    index: int
    page_start: int | None = None
    page_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None


SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "]


def recursive_split(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    normalized = " ".join(text.replace("\r", "\n").split())
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [normalized]
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        target_end = min(start + chunk_size, len(normalized))
        end = _best_boundary(normalized, start, target_end)
        piece = normalized[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(normalized):
            break
        start = max(0, end - overlap)
        while start < len(normalized) and normalized[start].isspace():
            start += 1
    return chunks


def _best_boundary(text: str, start: int, target_end: int) -> int:
    if target_end >= len(text):
        return len(text)
    window_start = max(start + 1, target_end - 180)
    window = text[window_start:target_end]
    for separator in SEPARATORS:
        location = window.rfind(separator)
        if location > 0:
            return window_start + location + len(separator)
    return target_end


def chunks_from_pages(pages: list[tuple[int, str]], chunk_size: int, overlap: int) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for page_number, page_text in pages:
        for text in recursive_split(page_text, chunk_size, overlap):
            chunks.append(
                TextChunk(
                    text=text,
                    index=len(chunks),
                    page_start=page_number,
                    page_end=page_number,
                )
            )
    return chunks
