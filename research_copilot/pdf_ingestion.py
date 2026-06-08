from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import fitz

from research_copilot.chunking import TextChunk
from research_copilot.config import Settings
from research_copilot.database import Database
from research_copilot.embeddings import EmbeddingService
from research_copilot.hashing import sha256_file
from research_copilot.vector_store import VectorStore


@dataclass(frozen=True)
class IngestResult:
    document_id: int
    chunk_count: int
    is_duplicate: bool
    page_count: int = 0
    status: str = "ready"
    message: str = ""


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int
    lines: list[str]


@dataclass(frozen=True)
class PdfExtraction:
    metadata: dict[str, str]
    pages: list[ExtractedPage]
    page_count: int
    status: str
    message: str


def ingest_pdf(
    settings: Settings,
    db: Database,
    embedder: EmbeddingService,
    vector_store: VectorStore,
    workspace_id: int,
    chat_id: int,
    uploaded_file: BinaryIO,
) -> IngestResult:
    file_name = Path(getattr(uploaded_file, "name", "document.pdf")).name
    staging_path = settings.uploads_dir / "_staging" / file_name
    staging_path.parent.mkdir(parents=True, exist_ok=True)

    with staging_path.open("wb") as handle:
        uploaded_file.seek(0)
        shutil.copyfileobj(uploaded_file, handle)

    digest = sha256_file(staging_path)
    existing = db.find_document_by_sha(workspace_id, digest)
    if existing:
        staging_path.unlink(missing_ok=True)
        existing_id = int(existing["id"])
        if db.count_chunks_for_document(existing_id) == 0:
            return _process_existing_document(
                settings,
                db,
                embedder,
                vector_store,
                existing_id,
                workspace_id,
                existing.get("chat_id") or chat_id,
                existing["file_name"],
                Path(existing["file_path"]),
                is_duplicate=True,
            )
        return IngestResult(
            document_id=existing_id,
            chunk_count=db.count_chunks_for_document(existing_id),
            is_duplicate=True,
            page_count=int(existing.get("page_count") or 0),
            status=_metadata_status(existing.get("metadata_json")),
            message="Document already exists.",
        )

    document_dir = settings.uploads_dir / str(workspace_id) / str(chat_id)
    document_dir.mkdir(parents=True, exist_ok=True)
    destination = document_dir / f"{digest}_{file_name}"
    shutil.move(str(staging_path), destination)

    extraction = _extract_pdf(destination)
    document_id = db.add_document(
        workspace_id=workspace_id,
        chat_id=chat_id,
        file_name=file_name,
        file_path=str(destination),
        mime_type="application/pdf",
        sha256=digest,
        title=extraction.metadata.get("title") or None,
        author=extraction.metadata.get("author") or None,
        page_count=extraction.page_count,
        metadata=_with_ingest_metadata(extraction),
    )
    return _store_chunks_for_extraction(
        db,
        embedder,
        vector_store,
        document_id,
        workspace_id,
        chat_id,
        file_name,
        extraction,
        settings.chunk_size,
        settings.chunk_overlap,
        is_duplicate=False,
    )


def _process_existing_document(
    settings: Settings,
    db: Database,
    embedder: EmbeddingService,
    vector_store: VectorStore,
    document_id: int,
    workspace_id: int,
    chat_id: int,
    file_name: str,
    path: Path,
    is_duplicate: bool = False,
) -> IngestResult:
    extraction = _extract_pdf(path)
    db.delete_chunks_for_document(document_id)
    db.update_document_ingestion(
        document_id,
        extraction.page_count,
        _with_ingest_metadata(extraction),
        title=extraction.metadata.get("title") or None,
        author=extraction.metadata.get("author") or None,
    )
    return _store_chunks_for_extraction(
        db,
        embedder,
        vector_store,
        document_id,
        workspace_id,
        chat_id,
        file_name,
        extraction,
        settings.chunk_size,
        settings.chunk_overlap,
        is_duplicate=is_duplicate,
    )


def reprocess_document(
    settings: Settings,
    db: Database,
    embedder: EmbeddingService,
    vector_store: VectorStore,
    document_id: int,
) -> IngestResult:
    document = db.get_document(document_id)
    if not document:
        return IngestResult(document_id=document_id, chunk_count=0, is_duplicate=False, status="missing")
    return _process_existing_document(
        settings,
        db,
        embedder,
        vector_store,
        document_id,
        int(document["workspace_id"]),
        int(document.get("chat_id") or 0),
        str(document["file_name"]),
        Path(document["file_path"]),
    )


def _store_chunks_for_extraction(
    db: Database,
    embedder: EmbeddingService,
    vector_store: VectorStore,
    document_id: int,
    workspace_id: int,
    chat_id: int,
    file_name: str,
    extraction: PdfExtraction,
    chunk_size: int,
    chunk_overlap: int,
    is_duplicate: bool,
) -> IngestResult:
    text_chunks = _chunks_from_extracted_pages(extraction.pages, chunk_size=chunk_size, overlap=chunk_overlap)
    chunk_rows = [
        {
            "document_id": document_id,
            "workspace_id": workspace_id,
            "chat_id": chat_id,
            "chunk_index": chunk.index,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
            "text": chunk.text,
            "token_count": len(chunk.text.split()),
        }
        for chunk in text_chunks
    ]
    chunk_ids = db.add_chunks(chunk_rows)
    stored_chunks = []
    for chunk_id, chunk in zip(chunk_ids, chunk_rows, strict=True):
        stored = dict(chunk)
        stored["id"] = chunk_id
        stored["file_name"] = file_name
        stored_chunks.append(stored)

    vectors = embedder.embed_texts([chunk["text"] for chunk in stored_chunks])
    vector_store.upsert_chunks(stored_chunks, vectors)
    return IngestResult(
        document_id=document_id,
        chunk_count=len(stored_chunks),
        is_duplicate=is_duplicate,
        page_count=extraction.page_count,
        status=extraction.status,
        message=extraction.message,
    )


def _extract_pdf(path: Path) -> PdfExtraction:
    doc = fitz.open(path)
    metadata = {key: str(value or "") for key, value in (doc.metadata or {}).items()}
    pages: list[ExtractedPage] = []
    saw_textless_page = False
    ocr_error = ""
    ocr_available = True
    
    md_chunks = []
    try:
        import pymupdf4llm
        # Using path as a string is highly reliable for pymupdf4llm
        md_chunks = pymupdf4llm.to_markdown(str(path), page_chunks=True)
    except ImportError:
        print("pymupdf4llm not installed, falling back to basic extraction")
    except Exception as e:
        print(f"pymupdf4llm extraction failed: {e}")

    tessdata = None
    if os.name == "nt" and not os.environ.get("TESSDATA_PREFIX"):
        common_paths = [
            r"C:\Program Files\Tesseract-OCR\tessdata",
            r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
            r"D:\Program Files\Tesseract-OCR\tessdata",
            r"C:\msys64\mingw64\share\tessdata",
        ]
        for tpath in common_paths:
            if os.path.exists(tpath):
                tessdata = tpath
                break

    pages_needing_ocr = []
    page_texts = {}

    for index, page in enumerate(doc, start=1):
        text = ""
        if index - 1 < len(md_chunks):
            text = md_chunks[index - 1].get("text", "").strip()
            
        if not text:
            text = page.get_text("text", sort=True).strip()
            
        if not text:
            pages_needing_ocr.append(index - 1)
        else:
            page_texts[index - 1] = text
            
    page_count = doc.page_count
    doc.close()

    ocr_error = ""
    saw_textless_page = len(pages_needing_ocr) > 0

    if pages_needing_ocr:
        import concurrent.futures
        # PyMuPDF Document objects are not thread-safe, but opening a separate 
        # Document object per thread allows fully parallel OCR processing.
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as executor:
            futures = [
                executor.submit(_ocr_page_worker, str(path), p_idx, tessdata)
                for p_idx in pages_needing_ocr
            ]
            for future in concurrent.futures.as_completed(futures):
                p_idx, text, err = future.result()
                if err:
                    ocr_error = err
                page_texts[p_idx] = text

    for index in range(page_count):
        text = page_texts.get(index, "")
        lines = _clean_lines(text)
        if lines:
            pages.append(ExtractedPage(page_number=index + 1, lines=lines))

    if pages:
        if saw_textless_page and ocr_error:
            status = "partial_text"
            message = f"Some pages had no selectable text. OCR encountered errors: {ocr_error}"
        else:
            status = "ready"
            message = "PDF text extracted."
    elif page_count:
        status = "ocr_unavailable" if ocr_error else "empty_text"
        message = (
            f"This PDF has {page_count} pages but no selectable text. OCR encountered errors: {ocr_error}"
            if ocr_error
            else f"This PDF has {page_count} pages but no selectable text."
        )
    else:
        status = "empty_pdf"
        message = "This PDF has no pages."
    return PdfExtraction(metadata=metadata, pages=pages, page_count=page_count, status=status, message=message)


import os

def _ocr_page_worker(path: str, index: int, tessdata: str | None) -> tuple[int, str, str]:
    import fitz
    doc = fitz.open(path)
    page = doc[index]
    try:
        if tessdata:
            textpage = page.get_textpage_ocr(language="eng", dpi=100, full=True, tessdata=tessdata)
        else:
            textpage = page.get_textpage_ocr(language="eng", dpi=100, full=True)
        text = page.get_text("text", textpage=textpage).strip()
        doc.close()
        return index, text, ""
    except Exception as exc:
        doc.close()
        return index, "", f"{exc.__class__.__name__}: {exc}"


def _clean_lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def _chunks_from_extracted_pages(pages: list[ExtractedPage], chunk_size: int, overlap: int) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for page in pages:
        current: list[tuple[int, str]] = []
        current_len = 0
        for line_number, line in enumerate(page.lines, start=1):
            next_len = current_len + len(line) + (1 if current else 0)
            if current and next_len > chunk_size:
                _append_line_chunk(chunks, page.page_number, current)
                current = _overlap_lines(current, overlap)
                current_len = sum(len(item[1]) for item in current) + max(0, len(current) - 1)
            current.append((line_number, line))
            current_len += len(line) + (1 if current_len else 0)
        if current:
            _append_line_chunk(chunks, page.page_number, current)
    return chunks


def _append_line_chunk(chunks: list[TextChunk], page_number: int, lines: list[tuple[int, str]]) -> None:
    chunks.append(
        TextChunk(
            text="\n".join(line for _number, line in lines).strip(),
            index=len(chunks),
            page_start=page_number,
            page_end=page_number,
            line_start=lines[0][0],
            line_end=lines[-1][0],
        )
    )


def _overlap_lines(lines: list[tuple[int, str]], overlap: int) -> list[tuple[int, str]]:
    if overlap <= 0:
        return []
    kept: list[tuple[int, str]] = []
    total = 0
    for item in reversed(lines):
        kept.append(item)
        total += len(item[1])
        if total >= overlap:
            break
    return list(reversed(kept))


def _with_ingest_metadata(extraction: PdfExtraction) -> dict[str, str]:
    metadata = dict(extraction.metadata)
    metadata["ingest_status"] = extraction.status
    metadata["ingest_message"] = extraction.message
    return metadata


def _metadata_status(metadata_json: str | None) -> str:
    if not metadata_json:
        return "ready"
    try:
        return str(json.loads(metadata_json).get("ingest_status") or "ready")
    except Exception:
        return "ready"
