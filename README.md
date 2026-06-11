# Research Copilot

Research Copilot is a local Retrieval-Augmented Generation (RAG) architecture designed for academic literature and dataset analysis. It supports PDF ingestion, Optical Character Recognition (OCR) pipeline fallback, vision-model integrations, and local LLM orchestration. 

All processing is executed on-premise, ensuring data privacy and local hardware utilization.

---

## Capabilities & Architecture

- **Local Processing Pipeline:** Integrates `Ollama` for local LLM inference and `ChromaDB` for vector similarity search. Operations are strictly local; no external API calls are made for embedding or generation.
- **Deep Research (Map-Reduce):** Implements an autonomous background agent utilizing a Map-Reduce architecture. It iterates over document chunks to extract context-specific findings, synthesizing them into a comprehensive, cited markdown report.
- **Data Analyst Mode:** Supports ingestion of `.csv` and `.xlsx` datasets. The system instantiates a local Python execution environment, pre-loading data into pandas `DataFrames`. The LLM can generate Python scripts for numerical analysis and matplotlib/seaborn plotting. Code execution and stdout/plot capture are handled automatically.
- **PDF Ingestion & Fallback OCR:** Extracts text from PDFs using `PyMuPDF`. Implements a fallback mechanism to `Tesseract OCR` for scanned documents lacking a native text layer, utilizing multithreaded image extraction and processing.
- **Multi-Modal Vision Integration:** Supports image array payloads in the chat composer. Integrates with local vision models (e.g., `llava`) for joint visual-linguistic query resolution.
- **Semantic Highlighting:** Generates deterministic markdown citations (e.g., `[1]`). The backend maps these citations to exact line numbers and bounding boxes, rendering semantic highlights over the original PDF bytes via a PyMuPDF highlighting engine.
- **Knowledge Graphs & GraphRAG:** Extracts entities and relationships during ingestion to construct an interconnected PyVis/NetworkX knowledge graph. The retrieval pipeline queries these graph edges to inject explicit multi-hop relational context into the prompt schema.
- **Document Comparison:** Generates lexical and semantic comparisons between two documents, outlining overlapping and disjoint context spaces.
- **Literature Review Synthesis:** Triggers a batch summarization job across the active workspace, outputting a synthesized review.
- **Export Formats:** Serializes chat history, citations, and images to Markdown, PDF, and DOCX formats.
- **User Interface:** Implemented in vanilla JS/HTML/CSS. Features responsive flexbox layouts, CSS-based state toggles, clipboard integration, and asynchronous DOM updates.
- **Native Desktop Mode:** Wraps the FastAPI backend in a `pywebview` container to execute as a standalone desktop application.

---

## Prerequisites

1. **Python 3.10+**: Must be present in the system PATH.
2. **Ollama**: Required for local LLM and embedding processes.
   - Recommended setup for text and vision capabilities:
     ```bash
     ollama run llama3:8b-instruct
     ollama pull llava
     ```
3. **Tesseract OCR (Optional):** Required for OCR fallback on scanned PDFs.
   - **Windows:** Download from [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki). The application checks `C:\Program Files\Tesseract-OCR` by default.

---

## Installation

1. Clone or download the repository.
2. Initialize a virtual environment:
   ```bash
   python -m venv .venv
   ```
3. Activate the environment:
   - Windows: `.venv\Scripts\activate`
   - Unix/MacOS: `source .venv/bin/activate`
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Execution

### Option A: Standard Web Server
Execute the FastAPI server directly.
```bash
python fast_app.py
```
Navigate to `http://localhost:8502` via a web browser.

### Option B: Native Desktop Application
Execute the desktop wrapper.
```bash
python desktop_app.py
```
This spawns a `pywebview` window bound to the local server.

---

## System Stack

* **Backend:** FastAPI (Python)
* **Frontend:** Vanilla JavaScript, HTML, CSS
* **Vector Store:** ChromaDB
* **Embeddings:** `sentence-transformers`
* **Inference Engine:** Ollama API
* **Graphing Engine:** PyVis, NetworkX
* **PDF Processing:** PyMuPDF (fitz)
* **Framework Design:** Entirely custom-built from scratch. No bloated abstraction frameworks (e.g., LangChain, LlamaIndex) are utilized, ensuring maximum performance, transparent prompt management, and minimal dependency overhead.

## Troubleshooting

* **Inference Timeout:** Occurs when hardware constraints (RAM/VRAM) are exceeded by model size. Fall back to smaller quantized models (e.g., `phi3:mini`, `qwen2:1.5b-instruct`).
* **Tesseract Not Found:** Verify the 64-bit installation path. If not installed in `C:\Program Files\Tesseract-OCR\tessdata`, define a `TESSDATA_PREFIX` system environment variable pointing to the correct `tessdata` directory.
