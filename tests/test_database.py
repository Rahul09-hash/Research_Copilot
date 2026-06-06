from pathlib import Path

from research_copilot.database import Database


def test_database_persists_core_records(tmp_path: Path):
    db = Database(tmp_path / "research.sqlite")
    db.initialize()

    workspace_id = db.create_workspace("Test Workspace")
    chat_id = db.create_chat(workspace_id, "Test Chat")
    db.add_message(chat_id, "user", "What does the paper say?")

    document_id = db.add_document(
        workspace_id=workspace_id,
        chat_id=chat_id,
        file_name="paper.pdf",
        file_path=str(tmp_path / "paper.pdf"),
        mime_type="application/pdf",
        sha256="abc123",
        title="Paper",
        author="Researcher",
        page_count=1,
        metadata={"title": "Paper"},
    )
    chunk_ids = db.add_chunks(
        [
            {
                "document_id": document_id,
                "workspace_id": workspace_id,
                "chat_id": chat_id,
                "chunk_index": 0,
                "page_start": 1,
                "page_end": 1,
                "text": "Local RAG stores citations.",
            }
        ]
    )

    assert db.find_document_by_sha(workspace_id, "abc123")["id"] == document_id
    assert db.get_messages(chat_id)[0]["content"] == "What does the paper say?"
    assert db.get_chunk(chunk_ids[0])["file_name"] == "paper.pdf"


def test_notes_and_summary(tmp_path: Path):
    db = Database(tmp_path / "research.sqlite")
    db.initialize()

    workspace_id = db.ensure_workspace("Default Workspace")
    chat_id = db.ensure_chat(workspace_id, "Research Chat")
    db.add_note(workspace_id, chat_id, "Idea", "Follow up on hybrid retrieval.")
    db.add_message(chat_id, "user", "Summarize this.")
    db.update_conversation_summary(chat_id)

    assert db.list_notes(workspace_id, chat_id)[0]["title"] == "Idea"
    assert "Summarize this." in db.get_conversation_summary(chat_id)
