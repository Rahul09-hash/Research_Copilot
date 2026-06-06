from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from research_copilot.config import Settings, ensure_data_dirs
from research_copilot.database import Database
from research_copilot.embeddings import EmbeddingService
from research_copilot.graph import KnowledgeGraphBuilder
from research_copilot.llm import LocalLLM
from research_copilot.rag import RAGEngine
from research_copilot.search import HybridRetriever
from research_copilot.vector_store import VectorStore


@dataclass(frozen=True)
class Services:
    settings: Settings
    db: Database
    embedder: EmbeddingService
    vector_store: VectorStore
    retriever: HybridRetriever
    rag: RAGEngine
    graph_builder: KnowledgeGraphBuilder


@lru_cache(maxsize=1)
def get_services() -> Services:
    settings = Settings.from_env()
    ensure_data_dirs(settings)
    db = Database(settings.database_path)
    db.initialize()
    embedder = EmbeddingService(
        settings.embedding_model,
        settings.models_dir,
        provider=settings.embedding_provider,
    )
    vector_store = VectorStore(settings.qdrant_path, settings.collection_name, embedder.dimension)
    retriever = HybridRetriever(db, vector_store, embedder, settings)
    rag = RAGEngine(
        db,
        retriever,
        LocalLLM(
            settings.ollama_host,
            settings.ollama_model,
            settings.ollama_num_ctx,
            settings.ollama_num_predict,
        ),
        settings,
    )
    return Services(
        settings=settings,
        db=db,
        embedder=embedder,
        vector_store=vector_store,
        retriever=retriever,
        rag=rag,
        graph_builder=KnowledgeGraphBuilder(db, settings),
    )
