from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from research_copilot.config import Settings
from research_copilot.database import Database
from research_copilot.embeddings import EmbeddingService
from research_copilot.vector_store import VectorStore


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    file_name: str
    text: str
    page_start: int | None
    page_end: int | None
    line_start: int | None
    line_end: int | None
    score: float
    semantic_score: float
    keyword_score: float


class HybridRetriever:
    def __init__(self, db: Database, vector_store: VectorStore, embedder: EmbeddingService, settings: Settings):
        self.db = db
        self.vector_store = vector_store
        self.embedder = embedder
        self.settings = settings
        self.reranker = None
        self.reranker_status = "not-loaded"

    def retrieve(self, workspace_id: int, query: str, limit: int | None = None) -> list[RetrievedChunk]:
        limit = limit or self.settings.retrieval_k
        chunks = self.db.get_chunks_for_workspace(workspace_id)
        if not chunks:
            return []

        query_vector = self.embedder.embed_query(query)
        semantic_hits = self.vector_store.search(workspace_id, query_vector, limit=max(limit * 4, 20))
        semantic_scores = {hit.chunk_id: hit.score for hit in semantic_hits}
        keyword_scores = self._keyword_scores(query, chunks)

        semantic_norm = _normalize(semantic_scores)
        keyword_norm = _normalize(keyword_scores)

        chunk_by_id = {int(chunk["id"]): chunk for chunk in chunks}
        candidate_ids = set(semantic_norm) | set(keyword_norm)
        if not candidate_ids:
            candidate_ids = {int(chunk["id"]) for chunk in chunks[:limit]}

        results: list[RetrievedChunk] = []
        for chunk_id in candidate_ids:
            chunk = chunk_by_id.get(chunk_id)
            if not chunk:
                continue
            semantic = semantic_norm.get(chunk_id, 0.0)
            keyword = keyword_norm.get(chunk_id, 0.0)
            score = (0.65 * semantic) + (0.35 * keyword)
            results.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    document_id=int(chunk["document_id"]),
                    file_name=str(chunk["file_name"]),
                    text=str(chunk["text"]),
                    page_start=chunk.get("page_start"),
                    page_end=chunk.get("page_end"),
                    line_start=chunk.get("line_start"),
                    line_end=chunk.get("line_end"),
                    score=score,
                    semantic_score=semantic,
                    keyword_score=keyword,
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        results = results[: max(limit * 2, limit)]
        return self._rerank(query, results)[:limit]

    def _keyword_scores(self, query: str, chunks: list[dict[str, Any]]) -> dict[int, float]:
        tokenized_corpus = [_tokenize(str(chunk["text"])) for chunk in chunks]
        tokenized_query = _tokenize(query)
        if not tokenized_query:
            return {}

        try:
            from rank_bm25 import BM25Okapi

            bm25 = BM25Okapi(tokenized_corpus)
            scores = bm25.get_scores(tokenized_query)
            return {int(chunk["id"]): float(score) for chunk, score in zip(chunks, scores, strict=True)}
        except Exception:
            return {
                int(chunk["id"]): _simple_keyword_score(tokenized_query, tokens)
                for chunk, tokens in zip(chunks, tokenized_corpus, strict=True)
            }

    def _rerank(self, query: str, results: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not self.settings.reranker_enabled:
            self.reranker_status = "disabled"
            return results
        if len(results) < 2:
            return results
        if self.reranker is None and self.reranker_status == "not-loaded":
            try:
                from sentence_transformers import CrossEncoder

                self.reranker = CrossEncoder(
                    self.settings.reranker_model,
                    cache_folder=str(self.settings.models_dir),
                    local_files_only=True,
                )
                self.reranker_status = self.settings.reranker_model
            except Exception as exc:  # pragma: no cover - depends on local model cache
                self.reranker_status = f"unavailable ({exc.__class__.__name__})"
        if self.reranker is None:
            return results

        pairs = [(query, result.text) for result in results]
        rerank_scores = self.reranker.predict(pairs)
        adjusted: list[RetrievedChunk] = []
        normalized = _normalize({index: float(score) for index, score in enumerate(rerank_scores)})
        for index, result in enumerate(results):
            score = (0.4 * result.score) + (0.6 * normalized.get(index, 0.0))
            adjusted.append(
                RetrievedChunk(
                    chunk_id=result.chunk_id,
                    document_id=result.document_id,
                    file_name=result.file_name,
                    text=result.text,
                    page_start=result.page_start,
                    page_end=result.page_end,
                    line_start=result.line_start,
                    line_end=result.line_end,
                    score=score,
                    semantic_score=result.semantic_score,
                    keyword_score=result.keyword_score,
                )
            )
        adjusted.sort(key=lambda item: item.score, reverse=True)
        return adjusted


def _tokenize(text: str) -> list[str]:
    # Include Unicode characters, Greek letters, and digits for scientific BM25 tokenization
    return re.findall(r"[\wα-ωΑ-ΩµΦΨΩΘΛΣΠΔΓΞ]+", text.lower())


def _simple_keyword_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    if not doc_tokens:
        return 0.0
    counts = {token: doc_tokens.count(token) for token in set(query_tokens)}
    score = sum(counts.values())
    return score / math.sqrt(len(doc_tokens))


def _normalize(scores: dict[int, float]) -> dict[int, float]:
    if not scores:
        return {}
    values = list(scores.values())
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return {key: 1.0 if value > 0 else 0.0 for key, value in scores.items()}
    return {key: (value - minimum) / (maximum - minimum) for key, value in scores.items()}
