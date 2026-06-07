from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from research_copilot.comparison import compare_documents
from research_copilot.config import Settings
from research_copilot.database import Database
from research_copilot.embeddings import EmbeddingService
from research_copilot.exports import export_chat_docx, export_chat_markdown, export_chat_pdf
from research_copilot.graph import KnowledgeGraphBuilder
from research_copilot.pdf_ingestion import ingest_pdf
from research_copilot.rag import RAGEngine
from research_copilot.service_factory import get_services as get_core_services
from research_copilot.vector_store import VectorStore


st.set_page_config(page_title="Research Copilot", page_icon="RC", layout="wide")

# ---------------------------------------------------------------------------
# Math-aware message rendering
# ---------------------------------------------------------------------------

_UNICODE_TO_LATEX: dict[str, str] = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\varepsilon", "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta",
    "ι": r"\iota", "κ": r"\kappa", "λ": r"\lambda", "μ": r"\mu", "µ": r"\mu",
    "ν": r"\nu", "ξ": r"\xi", "π": r"\pi", "ρ": r"\rho",
    "σ": r"\sigma", "τ": r"\tau", "υ": r"\upsilon", "φ": r"\phi",
    "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega",
    "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda",
    "Ξ": r"\Xi", "Π": r"\Pi", "Σ": r"\Sigma", "Φ": r"\Phi",
    "Ψ": r"\Psi", "Ω": r"\Omega",
    "×": r"\times", "·": r"\cdot", "÷": r"\div", "±": r"\pm",
    "≤": r"\leq", "≥": r"\geq", "≠": r"\neq", "≈": r"\approx",
    "∞": r"\infty", "∫": r"\int", "∑": r"\sum", "∏": r"\prod",
    "∂": r"\partial", "∇": r"\nabla", "∝": r"\propto",
    "→": r"\rightarrow", "←": r"\leftarrow",
    "⇌": r"\rightleftharpoons", "⇒": r"\Rightarrow",
    "₀": "_0", "₁": "_1", "₂": "_2", "₃": "_3", "₄": "_4",
    "₅": "_5", "₆": "_6", "₇": "_7", "₈": "_8", "₉": "_9",
    "⁰": "^0", "¹": "^1", "²": "^2", "³": "^3", "⁴": "^4",
}

def _to_latex(expr: str) -> str:
    """Convert plain-text math expression to LaTeX for st.latex() rendering."""
    import re
    s = expr
    for uni, latex in _UNICODE_TO_LATEX.items():
        if latex.startswith("\\"):
            s = s.replace(uni, latex + " ")
        else:
            s = s.replace(uni, latex)
    s = re.sub(
        r"\bd([A-Za-z\\]+(?:\{[^}]+\})?)/d([A-Za-z]+)",
        lambda m: rf"\frac{{d{m.group(1)}}}{{d{m.group(2)}}}",
        s,
    )
    s = re.sub(r"(?<=[\w\d\)])\s*\*\s*(?=[\w\d\(\\])", r" \cdot ", s)
    s = re.sub(r"([A-Za-z]+|\\[A-Za-z]+)\s*(\d+)", r"\1_{\2}", s)
    return s

def _is_math_line(line: str) -> bool:
    import re
    s = line.strip()
    if not s:
        return False
    s_clean = re.sub(r"^(\d+\.|-|\*|\#|>|`)\s*", "", s).strip()
    english_words = re.findall(r"\b[a-zA-Z]{4,}\b", s_clean)
    if len(english_words) > 4:
        return False
    has_eq = "=" in s_clean or "≈" in s_clean or "->" in s_clean or "=>" in s_clean or "→" in s_clean
    has_math_chars = bool(re.search(r"[\+\-\*/\^∫∑∂∇]", s_clean))
    has_vars = bool(re.search(r"[α-ωΑ-ΩµΦΨΩΘΛΣΠΔΓΞ]", s_clean))
    return has_eq or (has_math_chars and has_vars)

def _format_inline_math(text: str) -> str:
    import re
    line = re.sub(r"([α-ωΑ-ΩµΦΨΩΘΛΣΠΔΓΞ]+[A-Za-z0-9_]*)", r"$\1$", text)
    line = re.sub(r"\b([A-Za-z]\d+)\b", r"$\1$", line)
    def _latex_repl(m):
        return f"${_to_latex(m.group(1).strip())}$"
    line = re.sub(r"\$([^\$]+)\$", _latex_repl, line)
    return line

def _process_plain_segment(text: str) -> None:
    import re
    text = re.sub(r"^(#{1,6})\s+(.*)", r"\n\n\1 \2\n\n", text, flags=re.MULTILINE)
    lines = text.splitlines()
    prose_buf: list[str] = []
    
    def _flush_prose() -> None:
        chunk = "\n".join(prose_buf).strip()
        if chunk:
            st.markdown(_format_inline_math(chunk))
        prose_buf.clear()
        
    for line in lines:
        s_line = line.strip()
        if not s_line:
            _flush_prose()
            continue
            
        parts = re.split(r"(?<=[.:])\s+", s_line)
        
        if _is_math_line(s_line):
            _flush_prose()
            clean_math = re.sub(r"^>\s*", "", s_line).strip()
            st.latex(_to_latex(clean_math))
        elif len(parts) > 1 and _is_math_line(parts[-1]):
            prose_buf.append(" ".join(parts[:-1]))
            _flush_prose()
            clean_math = re.sub(r"^>\s*", "", parts[-1]).strip()
            st.latex(_to_latex(clean_math))
        elif s_line.startswith("#"):
            _flush_prose()
            st.markdown(s_line)
        else:
            prose_buf.append(s_line)
            
    _flush_prose()

def _render_message(text: str) -> None:
    import re
    parts = re.split(r"(\$\$[\s\S]*?\$\$)", text)
    for part in parts:
        if part.startswith("$$") and part.endswith("$$") and len(part) > 4:
            latex_body = part[2:-2].strip()
            if latex_body:
                st.latex(_to_latex(latex_body))
        else:
            if part.strip():
                _process_plain_segment(part)

@st.cache_resource
def get_services() -> tuple[Settings, Database, EmbeddingService, VectorStore, HybridRetriever, RAGEngine, KnowledgeGraphBuilder]:
    services = get_core_services()
    return (
        services.settings,
        services.db,
        services.embedder,
        services.vector_store,
        services.retriever,
        services.rag,
        services.graph_builder,
    )


def get_or_create_session(db: Database) -> tuple[int, int]:
    workspace_id = st.session_state.get("workspace_id")
    if workspace_id is None:
        workspace_id = db.ensure_workspace("Default Workspace")
        st.session_state.workspace_id = workspace_id

    chat_id = st.session_state.get("chat_id")
    if chat_id is None:
        chat_id = db.ensure_chat(workspace_id, "Research Chat")
        st.session_state.chat_id = chat_id

    return workspace_id, chat_id


def refresh_chat_selection(db: Database, workspace_id: int) -> int:
    chats = db.list_chats(workspace_id)
    if not chats:
        return db.create_chat(workspace_id, "Research Chat")
    current = st.session_state.get("chat_id")
    if current not in {chat["id"] for chat in chats}:
        current = chats[0]["id"]
        st.session_state.chat_id = current
    return current


def sidebar(settings: Settings, db: Database, embedder: EmbeddingService, vector_store: VectorStore) -> tuple[int, int, str]:
    with st.sidebar:
        st.title("Research Copilot")
        st.caption("Local research workspace")

        active_page = st.radio(
            "View",
            ["Chat", "Documents", "Notes", "Knowledge Graph", "Exports"],
            index=0,
            key="active_page",
        )

        workspaces = db.list_workspaces()
        if not workspaces:
            default_id = db.ensure_workspace("Default Workspace")
            workspaces = db.list_workspaces()
            st.session_state.workspace_id = default_id

        workspace_names = {workspace["name"]: workspace["id"] for workspace in workspaces}
        current_workspace_id = st.session_state.get("workspace_id", workspaces[0]["id"])
        current_workspace_name = next(
            (workspace["name"] for workspace in workspaces if workspace["id"] == current_workspace_id),
            workspaces[0]["name"],
        )
        selected_workspace = st.selectbox(
            "Workspace",
            options=list(workspace_names.keys()),
            index=list(workspace_names.keys()).index(current_workspace_name),
        )
        workspace_id = workspace_names[selected_workspace]
        st.session_state.workspace_id = workspace_id

        with st.form("new_workspace", clear_on_submit=True):
            workspace_name = st.text_input("New workspace")
            if st.form_submit_button("Create workspace") and workspace_name.strip():
                st.session_state.workspace_id = db.create_workspace(workspace_name.strip())
                st.rerun()

        chat_id = refresh_chat_selection(db, workspace_id)
        chats = db.list_chats(workspace_id)
        chat_labels = {f"{chat['title']} #{chat['id']}": chat["id"] for chat in chats}
        current_chat_label = next(
            (label for label, value in chat_labels.items() if value == chat_id),
            next(iter(chat_labels)),
        )
        selected_chat = st.selectbox(
            "Chat",
            options=list(chat_labels.keys()),
            index=list(chat_labels.keys()).index(current_chat_label),
        )
        chat_id = chat_labels[selected_chat]
        st.session_state.chat_id = chat_id

        with st.form("new_chat", clear_on_submit=True):
            chat_title = st.text_input("New chat")
            if st.form_submit_button("Create chat"):
                title = chat_title.strip() or "Research Chat"
                st.session_state.chat_id = db.create_chat(workspace_id, title)
                st.rerun()

        st.divider()
        st.caption("Local services")
        st.write(f"Embeddings: `{embedder.status}`")
        st.write(f"Reranker: `{'on' if settings.reranker_enabled else 'off'}`")
        st.write(f"Vectors: `{vector_store.status}`")
        st.write(f"Ollama: `{settings.ollama_model}`")

    return workspace_id, chat_id, active_page


def render_chat(settings: Settings, db: Database, rag: RAGEngine, workspace_id: int, chat_id: int) -> None:
    total_messages = db.count_messages(chat_id)
    if total_messages > settings.chat_history_limit:
        hidden = total_messages - settings.chat_history_limit
        st.caption(f"Showing the latest {settings.chat_history_limit} messages. {hidden} older messages are stored.")
    messages = db.get_recent_messages(chat_id, settings.chat_history_limit)
    for message in messages:
        with st.chat_message(message["role"]):
            _render_message(message["content"])
            citations = message.get("citations")
            if citations:
                with st.expander("Citations"):
                    for citation in citations:
                        st.markdown(
                            f"**[{citation['number']}] {citation['file_name']}** "
                            f"page {citation.get('page_start') or '?'}"
                        )
                        st.caption(citation["snippet"])

    prompt = st.chat_input("Ask about your workspace")
    if prompt:
        db.add_message(chat_id, "user", prompt)
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Retrieving local sources..."):
                prepared = rag.prepare_answer(workspace_id, chat_id, prompt)
            
            live = st.empty()
            full_response = ""
            for chunk in rag.stream_prepared(prepared):
                full_response += str(chunk)
                live.markdown(full_response + " ▌")
                
            live.empty()
            _render_message(full_response)
            
            saved_content = rag.with_sources(full_response, prepared.citations)
            source_block = rag.with_sources("", prepared.citations).strip() if prepared.citations else ""
            if source_block:
                st.markdown(source_block)
            if prepared.citations:
                with st.expander("Citations"):
                    for citation in prepared.citations:
                        st.markdown(
                            f"**[{citation['number']}] {citation['file_name']}** "
                            f"page {citation.get('page_start') or '?'}"
                        )
                        st.caption(citation["snippet"])
        db.add_message(chat_id, "assistant", saved_content, prepared.citations)
        db.update_conversation_summary(chat_id)


def render_documents(
    settings: Settings,
    db: Database,
    embedder: EmbeddingService,
    vector_store: VectorStore,
    graph_builder: KnowledgeGraphBuilder,
    workspace_id: int,
    chat_id: int,
) -> None:
    uploaded_files = st.file_uploader("Add PDFs", type=["pdf"], accept_multiple_files=True)
    if uploaded_files:
        for uploaded_file in uploaded_files:
            with st.spinner(f"Ingesting {uploaded_file.name}..."):
                result = ingest_pdf(settings, db, embedder, vector_store, workspace_id, chat_id, uploaded_file)
                if result.is_duplicate:
                    st.info(f"{uploaded_file.name} was already ingested in this workspace.")
                else:
                    graph_builder.build_for_document(result.document_id)
                    st.success(f"Ingested {uploaded_file.name}: {result.chunk_count} chunks.")

    documents = db.list_documents(workspace_id)
    if not documents:
        st.info("No documents uploaded yet.")
        return

    st.subheader("Documents")
    for doc in documents:
        with st.container():
            col1, col2 = st.columns([5, 1])
            with col1:
                st.markdown(f"**{doc['file_name']}** (ID: {doc['id']}, {doc['page_count']} pages)")
                st.caption(f"SHA256: {doc['sha256'][:12]} | Uploaded: {doc['created_at']}")
            with col2:
                if st.button("Delete", key=f"del_doc_{doc['id']}"):
                    vector_store.delete_chunks_for_document(doc["id"])
                    db.delete_document(doc["id"])
                    st.rerun()
            st.divider()


def render_notes(db: Database, workspace_id: int, chat_id: int) -> None:
    with st.form("note_form", clear_on_submit=True):
        title = st.text_input("Note title")
        body = st.text_area("Note")
        if st.form_submit_button("Save note") and (title.strip() or body.strip()):
            db.add_note(workspace_id, chat_id, title.strip() or "Untitled note", body.strip())
            st.rerun()

    notes = db.list_notes(workspace_id, chat_id)
    for note in notes:
        with st.expander(note["title"]):
            st.markdown(note["body"])
            st.caption(note["created_at"])


def render_graph(db: Database, graph_builder: KnowledgeGraphBuilder, workspace_id: int) -> None:
    if st.button("Regenerate knowledge graph"):
        graph_builder.rebuild_workspace(workspace_id)
        st.rerun()

    graph_path = graph_builder.settings.graphs_dir / f"workspace_{workspace_id}.html"
    if not graph_path.exists():
        rendered_path = graph_builder.render_workspace(workspace_id)
        graph_path = Path(rendered_path) if rendered_path else graph_path
    if graph_path and Path(graph_path).exists():
        components.html(Path(graph_path).read_text(encoding="utf-8"), height=650, scrolling=True)
    else:
        st.info("Upload PDFs to generate a knowledge graph.")


def render_exports(settings: Settings, db: Database, rag: RAGEngine, workspace_id: int, chat_id: int) -> None:
    st.subheader("Chat exports")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Export Markdown"):
            path = export_chat_markdown(settings, db, chat_id)
            st.success(f"Saved {path}")
    with col2:
        if st.button("Export DOCX"):
            path = export_chat_docx(settings, db, chat_id)
            st.success(f"Saved {path}")
    with col3:
        if st.button("Export PDF"):
            path = export_chat_pdf(settings, db, chat_id)
            st.success(f"Saved {path}")

    st.divider()
    st.subheader("Document comparison")
    documents = db.list_documents(workspace_id)
    if len(documents) >= 2:
        labels = {f"{doc['file_name']} #{doc['id']}": doc["id"] for doc in documents}
        left, right = st.columns(2)
        with left:
            doc_a = st.selectbox("First document", list(labels.keys()), key="compare_a")
        with right:
            doc_b = st.selectbox("Second document", list(labels.keys()), key="compare_b")
        if st.button("Compare documents"):
            st.markdown(compare_documents(db, labels[doc_a], labels[doc_b]))
    else:
        st.info("Upload at least two documents to compare them.")

    st.divider()
    st.subheader("Literature review")
    if st.button("Generate literature review"):
        with st.spinner("Generating a citation-grounded review..."):
            review = rag.literature_review(workspace_id, chat_id)
        st.markdown(review.content)


def main() -> None:
    settings, db, embedder, vector_store, retriever, rag, graph_builder = get_services()
    workspace_id, chat_id = get_or_create_session(db)
    workspace_id, chat_id, active_page = sidebar(settings, db, embedder, vector_store)

    if active_page == "Chat":
        render_chat(settings, db, rag, workspace_id, chat_id)
    elif active_page == "Documents":
        render_documents(settings, db, embedder, vector_store, graph_builder, workspace_id, chat_id)
    elif active_page == "Notes":
        render_notes(db, workspace_id, chat_id)
    elif active_page == "Knowledge Graph":
        render_graph(db, graph_builder, workspace_id)
    elif active_page == "Exports":
        render_exports(settings, db, rag, workspace_id, chat_id)


if __name__ == "__main__":
    main()
