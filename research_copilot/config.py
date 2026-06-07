from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    qdrant_path: Path
    uploads_dir: Path
    exports_dir: Path
    graphs_dir: Path
    models_dir: Path
    collection_name: str
    embedding_provider: str
    embedding_model: str
    reranker_model: str
    reranker_enabled: bool
    ollama_host: str
    ollama_model: str
    ollama_num_ctx: int
    ollama_num_predict: int
    chunk_size: int
    chunk_overlap: int
    retrieval_k: int
    max_context_chars: int
    chat_history_limit: int

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("RC_DATA_DIR", PROJECT_ROOT / "data")).expanduser()
        models_dir = Path(os.getenv("RC_MODELS_DIR", data_dir / "models")).expanduser()
        return cls(
            data_dir=data_dir,
            database_path=data_dir / "research_copilot.sqlite",
            qdrant_path=data_dir / "qdrant",
            uploads_dir=data_dir / "uploads",
            exports_dir=data_dir / "exports",
            graphs_dir=data_dir / "graphs",
            models_dir=models_dir,
            collection_name=os.getenv("RC_COLLECTION_NAME", "research_chunks"),
            embedding_provider=os.getenv("RC_EMBEDDING_PROVIDER", "hash").lower(),
            embedding_model=os.getenv("RC_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
            reranker_model=os.getenv("RC_RERANKER_MODEL", "BAAI/bge-reranker-base"),
            reranker_enabled=_env_bool("RC_RERANKER_ENABLED", default=False),
            ollama_host=os.getenv("RC_OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.getenv("RC_OLLAMA_MODEL", "llama3.2:latest"),
            ollama_num_ctx=int(os.getenv("RC_OLLAMA_NUM_CTX", "4096")),
            ollama_num_predict=int(os.getenv("RC_OLLAMA_NUM_PREDICT", "2048")),
            chunk_size=int(os.getenv("RC_CHUNK_SIZE", "800")),
            chunk_overlap=int(os.getenv("RC_CHUNK_OVERLAP", "150")),
            retrieval_k=int(os.getenv("RC_RETRIEVAL_K", "4")),
            max_context_chars=int(os.getenv("RC_MAX_CONTEXT_CHARS", "3600")),
            chat_history_limit=int(os.getenv("RC_CHAT_HISTORY_LIMIT", "30")),
        )


def ensure_data_dirs(settings: Settings) -> None:
    for path in [
        settings.data_dir,
        settings.qdrant_path,
        settings.uploads_dir,
        settings.exports_dir,
        settings.graphs_dir,
        settings.models_dir,
    ]:
        path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(settings.models_dir / "huggingface"))
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(settings.models_dir / "sentence_transformers"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(settings.models_dir / "transformers"))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
