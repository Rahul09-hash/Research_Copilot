from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research_copilot.config import Settings
from research_copilot.database import Database
from research_copilot.llm import LocalLLM
from research_copilot.search import HybridRetriever, RetrievedChunk


@dataclass(frozen=True)
class Answer:
    content: str
    citations: list[dict[str, Any]]


@dataclass(frozen=True)
class PreparedAnswer:
    chunks: list[RetrievedChunk]
    citations: list[dict[str, Any]]
    messages: list[dict[str, str]]
    fallback_content: str | None = None


class RAGEngine:
    def __init__(self, db: Database, retriever: HybridRetriever, llm: LocalLLM, settings: Settings):
        self.db = db
        self.retriever = retriever
        self.llm = llm
        self.settings = settings

    def answer(self, workspace_id: int, chat_id: int, question: str) -> Answer:
        prepared = self.prepare_answer(workspace_id, chat_id, question)
        if prepared.fallback_content:
            return Answer(prepared.fallback_content, prepared.citations)

        llm_result = self.llm.chat(prepared.messages)
        if llm_result.used_model:
            content = llm_result.content
        else:
            content = self._fallback_answer(prepared.chunks, llm_result.error)
        return Answer(content=self.with_sources(content, prepared.citations), citations=prepared.citations)

    def prepare_answer(self, workspace_id: int, chat_id: int, question: str) -> PreparedAnswer:
        chunks = self.retriever.retrieve(workspace_id, question)
        citations = _citations_from_chunks(chunks)
        if not chunks:
            return PreparedAnswer(
                chunks=[],
                citations=[],
                messages=[],
                fallback_content=(
                    "I could not find uploaded document context for that yet. "
                    "Add PDFs in the Documents tab and ask again."
                ),
            )

        context = _format_context(chunks, self.settings.max_context_chars)
        memory = self.db.get_conversation_summary(chat_id)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Research Copilot, a local research assistant. Answer ONLY from the supplied context. "
                    "CRITICAL: You MUST use inline bracket citations like [1] or [2] immediately after every factual claim or sentence. "
                    "Do not wait until the end of the paragraph to cite. Place the bracket citation directly in the text. "
                    "If the context is insufficient, say so. "
                    "For mathematics, physics, statistics, algorithms, and chemistry, explain the reasoning step by step "
                    "in plain language and keep standalone formulas inside $$ ... $$ blocks. Use simple LaTeX only inside "
                    "math blocks, such as \\frac{a}{b}, x_i, x^2, \\sqrt{x}, \\sum, \\int, and Greek commands. "
                    "Do not put raw backslash math in normal prose. For chemical reactions, write reactions as "
                    "$$\\ce{CH4 + 2 O2 -> CO2 + 2 H2O}$$ style equations when the context supports them. "
                    "If an equation or reaction is not visible in the retrieved context, say that it is not visible instead "
                    "of inventing it."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Conversation memory:\n{memory or 'None'}\n\n"
                    f"Context:\n{context}\n\nQuestion: {question}"
                ),
            },
        ]
        return PreparedAnswer(chunks=chunks, citations=citations, messages=messages)

    def stream_prepared(self, prepared: PreparedAnswer):
        if prepared.fallback_content:
            yield from _character_stream(prepared.fallback_content)
            return

        emitted = False
        try:
            for chunk in self.llm.stream_chat(prepared.messages):
                emitted = True
                yield chunk
            if not emitted:
                yield from _character_stream("The local model returned an empty response.")
        except Exception as exc:  # pragma: no cover - depends on local Ollama service
            yield from _character_stream(self._fallback_answer(prepared.chunks, f"{exc.__class__.__name__}: {exc}"))

    def literature_review(self, workspace_id: int, chat_id: int) -> Answer:
        documents = self.db.list_documents(workspace_id)
        if not documents:
            return Answer("Upload documents before generating a literature review.", [])
        query = (
            "central research questions, methods, datasets, findings, limitations, gaps, "
            "future work, and relationships between papers"
        )
        chunks = self.retriever.retrieve(workspace_id, query, limit=14)
        citations = _citations_from_chunks(chunks)
        context = _format_context(chunks, self.settings.max_context_chars * 2)
        messages = [
            {
                "role": "system",
                "content": (
                    "Write a concise literature review from the supplied research context. "
                    "Organize it with headings for themes, agreements, disagreements, limitations, and open questions. "
                    "CRITICAL: You MUST use inline bracket citations like [1] or [2] immediately after every claim. "
                    "If math or chemistry is central, preserve key equations in "
                    "$$ ... $$ blocks and use $$\\ce{...}$$ for chemical reactions."
                ),
            },
            {"role": "user", "content": context},
        ]
        llm_result = self.llm.chat(messages)
        if llm_result.used_model:
            content = llm_result.content
        else:
            content = self._fallback_literature_review(chunks, llm_result.error)
        return Answer(content=self.with_sources(content, citations), citations=citations)

    def with_sources(self, content: str, citations: list[dict[str, Any]]) -> str:
        return _append_sources(content, citations)

    def _fallback_answer(self, chunks: list[RetrievedChunk], error: str | None) -> str:
        lines = [
            "I found relevant local evidence, but Ollama did not return an answer.",
            "",
            f"Local model error: `{error or 'unknown'}`",
            "",
            "Most relevant evidence:",
        ]
        for number, chunk in enumerate(chunks[:5], start=1):
            lines.append(f"- [{number}] {chunk.text[:450].strip()}")
        return "\n".join(lines)

    def _fallback_literature_review(self, chunks: list[RetrievedChunk], error: str | None) -> str:
        lines = [
            "## Literature Review Draft",
            "",
            f"Ollama was unavailable, so this extractive draft is based on retrieved passages. Error: `{error or 'unknown'}`",
            "",
        ]
        for number, chunk in enumerate(chunks[:10], start=1):
            lines.append(f"### Source [{number}]")
            lines.append(chunk.text[:700].strip())
            lines.append("")
        return "\n".join(lines)


def _format_context(chunks: list[RetrievedChunk], max_chars: int) -> str:
    blocks = []
    used_chars = 0
    for number, chunk in enumerate(chunks, start=1):
        page = f"page {chunk.page_start}" if chunk.page_start else "page unknown"
        if chunk.line_start and chunk.line_end:
            line_range = f", lines {chunk.line_start}-{chunk.line_end}"
        elif chunk.line_start:
            line_range = f", line {chunk.line_start}"
        else:
            line_range = ""
        header = f"[{number}] {chunk.file_name}, {page}{line_range}\n"
        remaining = max_chars - used_chars - len(header)
        if remaining <= 0:
            break
        text = chunk.text[:remaining]
        blocks.append(f"{header}{text}")
        used_chars += len(header) + len(text)
    return "\n\n".join(blocks)


def _citations_from_chunks(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    citations = []
    for number, chunk in enumerate(chunks, start=1):
        citations.append(
            {
                "number": number,
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "file_name": chunk.file_name,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
                "url": f"/api/documents/{chunk.document_id}/pdf#page={chunk.page_start or 1}",
                "snippet": chunk.text[:500],
                "score": round(chunk.score, 4),
            }
        )
    return citations


def _append_sources(content: str, citations: list[dict[str, Any]]) -> str:
    if not citations:
        return content
    source_lines = ["", "### Sources"]
    for citation in citations:
        page = citation.get("page_start") or "?"
        source_lines.append(f"[{citation['number']}] {citation['file_name']}, page {page}")
    return content.rstrip() + "\n" + "\n".join(source_lines)


def _character_stream(text: str):
    for character in text:
        yield character
