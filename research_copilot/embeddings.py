from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Iterable


class EmbeddingService:
    """Embedding wrapper.

    The default hash provider is intentionally tiny and keeps the UI responsive on
    low-RAM laptops. Set RC_EMBEDDING_PROVIDER=sentence-transformers for the
    heavier BAAI model.
    """

    def __init__(
        self,
        model_name: str,
        cache_dir: Path | None = None,
        provider: str = "hash",
        fallback_dimension: int = 384,
    ):
        self.model_name = model_name
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.provider = provider
        self.dimension = fallback_dimension
        self.model = None
        self.status = "fast-hash (low RAM)"

        if self.provider in {"sentence-transformers", "sentence_transformers", "transformers"}:
            self.status = f"{model_name} (lazy)"
        elif self.provider != "hash":
            self.status = f"fast-hash (unknown provider: {self.provider})"

    def embed_texts(self, texts: Iterable[str]) -> list[list[float]]:
        items = list(texts)
        if not items:
            return []
        if self.provider in {"sentence-transformers", "sentence_transformers", "transformers"}:
            self._ensure_sentence_transformer()
        if self.model is not None:
            vectors = self.model.encode(items, normalize_embeddings=True, show_progress_bar=False)
            return [vector.tolist() for vector in vectors]
        return [self._hash_embedding(text) for text in items]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def _ensure_sentence_transformer(self) -> None:
        if self.model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(
                self.model_name,
                cache_folder=str(self.cache_dir) if self.cache_dir else None,
                local_files_only=True,
            )
            if hasattr(self.model, "get_embedding_dimension"):
                dimension = self.model.get_embedding_dimension()
            else:
                dimension = self.model.get_sentence_embedding_dimension()
            self.dimension = int(dimension or self.dimension)
            self.status = self.model_name
        except Exception as exc:  # pragma: no cover - depends on local model cache
            self.provider = "hash"
            self.status = f"fast-hash fallback ({exc.__class__.__name__})"

    def _hash_embedding(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]
