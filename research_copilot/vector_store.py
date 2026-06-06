from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import atexit


@dataclass(frozen=True)
class VectorHit:
    chunk_id: int
    score: float
    payload: dict[str, Any]


class VectorStore:
    def __init__(self, path: Path, collection_name: str, dimension: int):
        self.path = Path(path)
        self.collection_name = collection_name
        self.dimension = dimension
        self.client = None
        self.status = "unavailable"
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self.path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(self.path))
            collections = {collection.name for collection in self.client.get_collections().collections}
            if collection_name not in collections:
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
                )
            atexit.register(self.close)
            self.status = f"local-qdrant:{self.path}"
        except Exception as exc:  # pragma: no cover - depends on optional qdrant install
            self.status = f"unavailable ({exc.__class__.__name__})"

    def close(self) -> None:
        if self.client is None:
            return
        client = self.client
        self.client = None
        try:
            client.close()
        except Exception:
            pass

    def upsert_chunks(self, chunks: list[dict[str, Any]], vectors: list[list[float]]) -> None:
        if self.client is None or not chunks:
            return
        from qdrant_client.models import PointStruct

        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            points.append(
                PointStruct(
                    id=int(chunk["id"]),
                    vector=vector,
                    payload={
                        "chunk_id": int(chunk["id"]),
                        "workspace_id": int(chunk["workspace_id"]),
                        "chat_id": chunk.get("chat_id"),
                        "document_id": int(chunk["document_id"]),
                        "file_name": chunk.get("file_name"),
                        "page_start": chunk.get("page_start"),
                        "page_end": chunk.get("page_end"),
                        "chunk_index": chunk.get("chunk_index"),
                    },
                )
            )
        self.client.upsert(collection_name=self.collection_name, points=points)

    def search(self, workspace_id: int, query_vector: list[float], limit: int = 8) -> list[VectorHit]:
        if self.client is None:
            return []
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        query_filter = Filter(
            must=[FieldCondition(key="workspace_id", match=MatchValue(value=int(workspace_id)))]
        )
        try:
            hits = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=limit,
            )
        except AttributeError:  # qdrant-client 1.10+
            hits = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=limit,
            ).points
        return [VectorHit(chunk_id=int(hit.id), score=float(hit.score), payload=hit.payload or {}) for hit in hits]
