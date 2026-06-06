from __future__ import annotations

import collections
import re

from research_copilot.database import Database


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "are",
    "was",
    "were",
    "have",
    "has",
    "into",
    "their",
    "between",
    "using",
    "based",
    "which",
}


def compare_documents(db: Database, document_a_id: int, document_b_id: int) -> str:
    doc_a = db.get_document(document_a_id)
    doc_b = db.get_document(document_b_id)
    if not doc_a or not doc_b:
        return "One of the selected documents was not found."

    text_a = " ".join(chunk["text"] for chunk in db.get_chunks_for_document(document_a_id))
    text_b = " ".join(chunk["text"] for chunk in db.get_chunks_for_document(document_b_id))
    terms_a = _top_terms(text_a)
    terms_b = _top_terms(text_b)
    shared = [term for term in terms_a if term in terms_b][:12]
    only_a = [term for term in terms_a if term not in terms_b][:12]
    only_b = [term for term in terms_b if term not in terms_a][:12]

    return "\n".join(
        [
            f"### {doc_a['file_name']} vs {doc_b['file_name']}",
            "",
            f"**Shared themes:** {', '.join(shared) or 'No strong overlap detected.'}",
            "",
            f"**Distinct in {doc_a['file_name']}:** {', '.join(only_a) or 'No distinctive terms detected.'}",
            "",
            f"**Distinct in {doc_b['file_name']}:** {', '.join(only_b) or 'No distinctive terms detected.'}",
        ]
    )


def _top_terms(text: str, limit: int = 40) -> list[str]:
    tokens = [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z-]{2,}", text.lower())
        if token not in STOPWORDS and len(token) > 3
    ]
    return [term for term, _count in collections.Counter(tokens).most_common(limit)]
