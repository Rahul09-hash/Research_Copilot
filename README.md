# Research Copilot

Research Copilot is a powerful, fully-local Retrieval-Augmented Generation (RAG) application designed specifically for researchers, students, and academics. It allows you to upload large collections of PDFs, perform high-speed Optical Character Recognition (OCR), extract chemical and mathematical formulas, and interact with the text using a fully local AI engine.

Because this runs entirely on your hardware, **your data remains 100% private.**

---

## ✨ Features

- **100% Local Processing:** Uses `Ollama` for AI generation and `ChromaDB` for vector retrieval. No data is sent to the cloud.
- **Deep Research Mode (Map-Reduce):** Need an exhaustive meta-analysis? Toggle "Deep Research" to kick off an autonomous background agent that reads every single chunk across all your documents, extracts highly relevant findings, and synthesizes them into a massive, heavily cited final report.
- **Data Analyst Mode:** Upload CSV or Excel datasets and toggle this mode on to turn the AI into an Expert Data Scientist. The local Python execution environment automatically loads your datasets into pandas DataFrames, allowing the AI to instantly write and execute code, perform complex numerical analysis, and generate beautiful `matplotlib`/`seaborn` plots directly in the chat!
- **Advanced PDF Ingestion:** Upload any PDF. If it's a scanned document without embedded text, it automatically falls back to Tesseract OCR to extract the raw images using highly optimized multithreading.
- **Multi-Modal Vision:** Paste multiple screenshots and images directly into the chat composer. The app seamlessly integrates with local vision models (like `llava`) to answer complex questions about multiple images simultaneously.
- **Semantic PDF Highlighting:** Ask questions about your literature and get perfectly formatted markdown citations (`[1]`, `[2]`). The backend accurately filters false citations. Clicking a citation opens the PDF side-by-side with the exact sentence the AI used brilliantly highlighted in **yellow** using a custom backend PyMuPDF engine.
- **Knowledge Graphs & GraphRAG:** Automatically generates interactive visual relationship graphs of the most important concepts spanning across your entire workspace. The RAG engine actively queries these explicit connections during chat to provide heavily grounded, multi-hop reasoning. *(Note: The `co_occurs` label indicates two entities are frequently mentioned together without a strict causal relationship).*
- **Document Comparison:** Select two papers and instantly generate a lexical comparison highlighting shared themes and distinct focus areas.
- **Literature Reviews:** With one click, synthesize a comprehensive literature review from all documents in your current workspace.
- **Exports:** Export your entire chat history, including AI answers and citations, cleanly to Markdown, PDF, or DOCX formats.
- **Beautiful & Responsive UI:** Experience a highly polished, minimalist interface featuring animated CSS toggle switches, perfectly responsive chat layouts, one-click "Copy to Clipboard", and interactive plot/image viewers.
- **Native Desktop App Mode:** Run the application as a standalone, immersive desktop window (via WebView) without needing to use a standard web browser.

---

## 🛠️ Prerequisites

To run this application, you need the following installed on your machine:

1. **Python 3.10+**: Make sure Python is in your system PATH.
2. **Ollama**: Download and install [Ollama](https://ollama.com/) to run the local LLM.
   - Once installed, open your terminal and pull a fast model (e.g., Llama 3) and a vision model (e.g., LLaVA) if you plan to paste images:
     ```bash
     ollama run llama3:8b-instruct
     ollama pull llava
     ```
3. **Tesseract OCR (Optional but highly recommended)**: Required for reading "scanned" PDFs that lack a native text layer.
   - **Windows:** Download the installer from [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki). The app will automatically detect it if installed in `C:\Program Files\Tesseract-OCR`.

---

## 🚀 Installation

1. **Clone or Download** this repository to your local machine.
2. **Open a terminal** in the project directory.
3. **Create a virtual environment** (recommended):
   ```bash
   python -m venv .venv
   ```
4. **Activate the virtual environment**:
   - On Windows:
     ```bash
     .venv\Scripts\activate
     ```
   - On Mac/Linux:
     ```bash
     source .venv/bin/activate
     ```
5. **Install the required Python packages**:
   ```bash
   pip install -r requirements.txt
   ```

---

## 🖥️ How to Run

You have two options for running Research Copilot:

### Option A: Standard Web Server (Browser Mode)
Run the FastAPI backend directly. This is great for active development or if you prefer using Chrome/Edge.

```bash
python fast_app.py
```
*Then, open your web browser and navigate to `http://localhost:8502`*

### Option B: Native Desktop Application
Run the app in a standalone, immersive desktop window using `pywebview`. It behaves exactly like a native Windows application.

```bash
python desktop_app.py
```
*A new desktop window will automatically launch and connect to the local server.*

---

## ⚙️ Architecture

* **Backend:** FastAPI (Python)
* **Frontend:** Vanilla JS / HTML / CSS (No heavy JS frameworks, blazingly fast)
* **Vector Database:** ChromaDB
* **Embeddings:** `sentence-transformers` (runs locally)
* **LLM Engine:** Ollama API
* **Graphing Engine:** PyVis / NetworkX

## 💡 Troubleshooting

* **"LLM did not answer" Timeout**: This usually occurs when you try to run a model that is too heavy for your computer's RAM/VRAM. Try pulling a smaller model like `phi3:mini` or `qwen2:1.5b-instruct` and using that instead.
* **Tesseract Not Found**: Ensure you installed the 64-bit Windows version of Tesseract. The code looks for it in `C:\Program Files\Tesseract-OCR\tessdata`. If you installed it elsewhere, add a `TESSDATA_PREFIX` System Environment Variable pointing to your `tessdata` folder.
