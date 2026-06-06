# Research Copilot

Research Copilot is a fully local research workspace for persistent research chats, PDF ingestion, hybrid retrieval, citation-grounded RAG, notes, document comparison, knowledge graphs, and exports.

The app is designed for offline use. It stores application state in SQLite, vectors in a local Qdrant store, files under the project `data` directory, and uses local Ollama models for generation.

## Features

- Fast browser-native local UI served by Starlette/Uvicorn
- Optional Streamlit fallback
- Workspace and chat management
- Permanent chat history with exact restore
- PDF upload and SHA256 duplicate detection
- PyMuPDF metadata extraction
- Scanned-PDF detection with OCR-ready reprocessing
- Recursive chunking with 800 character chunks and 150 character overlap
- Low-RAM hash embeddings by default, with optional `BAAI/bge-small-en-v1.5`
- Local Qdrant vector store
- BM25 keyword search and hybrid retrieval
- Optional `BAAI/bge-reranker-base` reranking
- Citation-grounded answers through Ollama, defaulting to the lighter `llama3.2:latest`
- Conversation memory summaries
- Notes linked to workspaces and chats
- Document comparison
- Literature review draft generation
- Knowledge graph generation and PyVis visualization
- Markdown, DOCX, and PDF exports
- Unit tests

## Quick Start

```powershell
cd D:\Research_Copilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install local Ollama models:

```powershell
ollama pull llama3.2
```

The app defaults to a low-RAM profile:

```text
RC_EMBEDDING_PROVIDER=hash
RC_RERANKER_ENABLED=false
RC_OLLAMA_MODEL=llama3.2:latest
RC_RETRIEVAL_K=4
RC_MAX_CONTEXT_CHARS=3600
```

For higher retrieval quality on a machine with more RAM, set `RC_EMBEDDING_PROVIDER=sentence-transformers` and `RC_RERANKER_ENABLED=true`. The embedding and reranker models are loaded through `sentence-transformers` and cached inside `data/models` by default. For strict offline use, download/cache these models before disconnecting:

```powershell
$env:RC_MODELS_DIR='D:\Research_Copilot\data\models'
python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; SentenceTransformer('BAAI/bge-small-en-v1.5', cache_folder=r'D:\Research_Copilot\data\models'); CrossEncoder('BAAI/bge-reranker-base', cache_folder=r'D:\Research_Copilot\data\models')"
```

Run the faster local UI:

```powershell
uvicorn fast_app:app --host 127.0.0.1 --port 8501
```

Open:

```text
http://localhost:8501
```

Streamlit is still available as a fallback:

```powershell
streamlit run app.py --server.fileWatcherType=none --browser.gatherUsageStats=false
```

## Local Data Layout

```text
data/
  research_copilot.sqlite
  qdrant/
  uploads/
  exports/
  graphs/
  models/
```

Override paths and models with environment variables from `.env.example`.

## Tests

```powershell
pytest
```

The unit tests focus on durable local behavior: chunking, SHA256 hashing, and SQLite persistence.

## Docker

The Docker image runs the Streamlit app. Ollama should run on the host unless you extend the compose file with an Ollama service.

```powershell
docker compose up --build
```

## Notes

If Ollama or sentence-transformer models are not available yet, the app still stores chats, ingests PDFs, builds chunks, supports notes, and exports data. RAG responses will show the relevant citations and tell you what local model dependency is missing.

Scanned/image-only PDFs need Tesseract OCR installed for chunking. Without it, the app still stores the PDF, counts pages correctly, and marks the document as `ocr_unavailable` instead of pretending it read zero pages. After installing Tesseract, use the document card's Reprocess button.

Chat citations are stored separately from answer text and shown as compact links to the local PDF page and line range when available.

For best laptop responsiveness, keep `qwen3:8b` unloaded when you are not using it:

```powershell
ollama stop qwen3:8b
```
