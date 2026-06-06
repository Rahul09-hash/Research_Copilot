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
            st.markdown(message["content"])
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
            streamed_content = st.write_stream(_character_stream(rag.stream_prepared(prepared)))
            if not isinstance(streamed_content, str):
                streamed_content = "".join(str(item) for item in streamed_content)
            saved_content = rag.with_sources(streamed_content, prepared.citations)
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


def _character_stream(chunks):
    for chunk in chunks:
        for character in str(chunk):
            yield character


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
    st.dataframe(
        [
            {
                "ID": doc["id"],
                "File": doc["file_name"],
                "Pages": doc["page_count"],
                "SHA256": doc["sha256"][:12],
                "Uploaded": doc["created_at"],
            }
            for doc in documents
        ],
        width="stretch",
        hide_index=True,
    )


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
