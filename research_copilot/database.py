from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspace (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS chat (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id INTEGER NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS message (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL REFERENCES chat(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
                    content TEXT NOT NULL,
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS document (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id INTEGER NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
                    chat_id INTEGER REFERENCES chat(id) ON DELETE SET NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_document_workspace_sha
                    ON document(workspace_id, sha256);

                CREATE TABLE IF NOT EXISTS document_chunk (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
                    workspace_id INTEGER NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
                    chat_id INTEGER REFERENCES chat(id) ON DELETE SET NULL,
                    chunk_index INTEGER NOT NULL,
                    page_start INTEGER,
                    page_end INTEGER,
                    line_start INTEGER,
                    line_end INTEGER,
                    text TEXT NOT NULL,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_chunk_workspace ON document_chunk(workspace_id);
                CREATE INDEX IF NOT EXISTS idx_chunk_document ON document_chunk(document_id);

                CREATE TABLE IF NOT EXISTS note (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id INTEGER NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
                    chat_id INTEGER REFERENCES chat(id) ON DELETE SET NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS entity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id INTEGER NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'concept',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(workspace_id, name)
                );

                CREATE TABLE IF NOT EXISTS relationship (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id INTEGER NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
                    source_entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
                    target_entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
                    label TEXT NOT NULL DEFAULT 'related_to',
                    weight REAL NOT NULL DEFAULT 1.0,
                    document_id INTEGER REFERENCES document(id) ON DELETE CASCADE,
                    chunk_id INTEGER REFERENCES document_chunk(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(workspace_id, source_entity_id, target_entity_id, label, document_id, chunk_id)
                );

                CREATE TABLE IF NOT EXISTS conversation_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL UNIQUE REFERENCES chat(id) ON DELETE CASCADE,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            _ensure_column(conn, "document_chunk", "line_start", "INTEGER")
            _ensure_column(conn, "document_chunk", "line_end", "INTEGER")

    def ensure_workspace(self, name: str) -> int:
        existing = self.get_workspace_by_name(name)
        if existing:
            return existing["id"]
        return self.create_workspace(name)

    def create_workspace(self, name: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute("INSERT INTO workspace(name) VALUES (?)", (name,))
            return int(cursor.lastrowid)

    def get_workspace_by_name(self, name: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM workspace WHERE name = ?", (name,)).fetchone()
            return dict(row) if row else None

    def list_workspaces(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM workspace ORDER BY updated_at DESC, id DESC").fetchall()
            return [dict(row) for row in rows]

    def ensure_chat(self, workspace_id: int, title: str) -> int:
        chats = self.list_chats(workspace_id)
        if chats:
            return chats[0]["id"]
        return self.create_chat(workspace_id, title)

    def create_chat(self, workspace_id: int, title: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO chat(workspace_id, title) VALUES (?, ?)",
                (workspace_id, title),
            )
            return int(cursor.lastrowid)

    def list_chats(self, workspace_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat WHERE workspace_id = ? ORDER BY updated_at DESC, id DESC",
                (workspace_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def add_message(self, chat_id: int, role: str, content: str, citations: list[dict[str, Any]] | None = None) -> int:
        citations_json = json.dumps(citations or [], ensure_ascii=True)
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO message(chat_id, role, content, citations_json) VALUES (?, ?, ?, ?)",
                (chat_id, role, content, citations_json),
            )
            conn.execute("UPDATE chat SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (chat_id,))
            return int(cursor.lastrowid)

    def get_messages(self, chat_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM message WHERE chat_id = ? ORDER BY id ASC",
                (chat_id,),
            ).fetchall()
        return _decode_messages(rows)

    def get_recent_messages(self, chat_id: int, limit: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM message
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        return list(reversed(_decode_messages(rows)))

    def count_messages(self, chat_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM message WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            return int(row["total"])

    def add_document(
        self,
        workspace_id: int,
        chat_id: int,
        file_name: str,
        file_path: str,
        mime_type: str,
        sha256: str,
        title: str | None,
        author: str | None,
        page_count: int,
        metadata: dict[str, Any],
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO document(
                    workspace_id, chat_id, file_name, file_path, mime_type, sha256,
                    title, author, page_count, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    chat_id,
                    file_name,
                    file_path,
                    mime_type,
                    sha256,
                    title,
                    author,
                    page_count,
                    json.dumps(metadata, ensure_ascii=True),
                ),
            )
            return int(cursor.lastrowid)

    def find_document_by_sha(self, workspace_id: int, sha256: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM document WHERE workspace_id = ? AND sha256 = ?",
                (workspace_id, sha256),
            ).fetchone()
            return dict(row) if row else None

    def list_documents(self, workspace_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT d.*, COUNT(c.id) AS chunk_count
                FROM document d
                LEFT JOIN document_chunk c ON c.document_id = d.id
                WHERE d.workspace_id = ?
                GROUP BY d.id
                ORDER BY d.created_at DESC, d.id DESC
                """,
                (workspace_id,),
            ).fetchall()
            documents = []
            for row in rows:
                item = dict(row)
                item["metadata"] = json.loads(item.get("metadata_json") or "{}")
                documents.append(item)
            return documents

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM document WHERE id = ?", (document_id,)).fetchone()
            return dict(row) if row else None

    def delete_document(self, document_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM document WHERE id = ?", (document_id,))

    def add_chunks(self, chunks: Iterable[dict[str, Any]]) -> list[int]:
        inserted: list[int] = []
        with self.connect() as conn:
            for chunk in chunks:
                cursor = conn.execute(
                    """
                    INSERT INTO document_chunk(
                        document_id, workspace_id, chat_id, chunk_index,
                        page_start, page_end, line_start, line_end, text, token_count
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["document_id"],
                        chunk["workspace_id"],
                        chunk.get("chat_id"),
                        chunk["chunk_index"],
                        chunk.get("page_start"),
                        chunk.get("page_end"),
                        chunk.get("line_start"),
                        chunk.get("line_end"),
                        chunk["text"],
                        chunk.get("token_count", len(chunk["text"].split())),
                    ),
                )
                inserted.append(int(cursor.lastrowid))
        return inserted

    def delete_chunks_for_document(self, document_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM document_chunk WHERE document_id = ?", (document_id,))

    def count_chunks_for_document(self, document_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM document_chunk WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            return int(row["total"])

    def update_document_ingestion(
        self,
        document_id: int,
        page_count: int,
        metadata: dict[str, Any],
        title: str | None = None,
        author: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE document
                SET page_count = ?, metadata_json = ?, title = COALESCE(?, title), author = COALESCE(?, author)
                WHERE id = ?
                """,
                (page_count, json.dumps(metadata, ensure_ascii=True), title, author, document_id),
            )

    def get_chunks_for_workspace(self, workspace_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, d.file_name, d.file_path
                FROM document_chunk c
                JOIN document d ON d.id = c.document_id
                WHERE c.workspace_id = ?
                ORDER BY c.id ASC
                """,
                (workspace_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_chunks_for_document(self, document_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, d.file_name, d.file_path
                FROM document_chunk c
                JOIN document d ON d.id = c.document_id
                WHERE c.document_id = ?
                ORDER BY c.chunk_index ASC
                """,
                (document_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_chunk(self, chunk_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT c.*, d.file_name, d.file_path
                FROM document_chunk c
                JOIN document d ON d.id = c.document_id
                WHERE c.id = ?
                """,
                (chunk_id,),
            ).fetchone()
            return dict(row) if row else None

    def add_note(self, workspace_id: int, chat_id: int, title: str, body: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO note(workspace_id, chat_id, title, body) VALUES (?, ?, ?, ?)",
                (workspace_id, chat_id, title, body),
            )
            return int(cursor.lastrowid)

    def list_notes(self, workspace_id: int, chat_id: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM note WHERE workspace_id = ?"
        params: list[Any] = [workspace_id]
        if chat_id is not None:
            query += " AND (chat_id = ? OR chat_id IS NULL)"
            params.append(chat_id)
        query += " ORDER BY updated_at DESC, id DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def upsert_entity(self, workspace_id: int, name: str, entity_type: str = "concept") -> int:
        normalized = name.strip()
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO entity(workspace_id, name, type) VALUES (?, ?, ?)",
                (workspace_id, normalized, entity_type),
            )
            row = conn.execute(
                "SELECT id FROM entity WHERE workspace_id = ? AND name = ?",
                (workspace_id, normalized),
            ).fetchone()
            return int(row["id"])

    def upsert_relationship(
        self,
        workspace_id: int,
        source_entity_id: int,
        target_entity_id: int,
        label: str,
        document_id: int | None,
        chunk_id: int | None,
    ) -> None:
        if source_entity_id == target_entity_id:
            return
        if source_entity_id > target_entity_id:
            source_entity_id, target_entity_id = target_entity_id, source_entity_id
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO relationship(
                    workspace_id, source_entity_id, target_entity_id, label,
                    weight, document_id, chunk_id
                )
                VALUES (?, ?, ?, ?, 1.0, ?, ?)
                ON CONFLICT(workspace_id, source_entity_id, target_entity_id, label, document_id, chunk_id)
                DO UPDATE SET weight = weight + 1.0
                """,
                (workspace_id, source_entity_id, target_entity_id, label, document_id, chunk_id),
            )

    def list_graph(self, workspace_id: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with self.connect() as conn:
            entities = [dict(row) for row in conn.execute(
                "SELECT * FROM entity WHERE workspace_id = ? ORDER BY name ASC",
                (workspace_id,),
            ).fetchall()]
            relationships = [dict(row) for row in conn.execute(
                """
                SELECT r.*, se.name AS source_name, te.name AS target_name
                FROM relationship r
                JOIN entity se ON se.id = r.source_entity_id
                JOIN entity te ON te.id = r.target_entity_id
                WHERE r.workspace_id = ?
                ORDER BY r.weight DESC
                """,
                (workspace_id,),
            ).fetchall()]
        return entities, relationships

    def clear_graph(self, workspace_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM relationship WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM entity WHERE workspace_id = ?", (workspace_id,))

    def update_conversation_summary(self, chat_id: int, max_messages: int = 12) -> None:
        messages = self.get_messages(chat_id)[-max_messages:]
        summary = "\n".join(f"{message['role']}: {message['content'][:500]}" for message in messages)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_summary(chat_id, summary)
                VALUES (?, ?)
                ON CONFLICT(chat_id)
                DO UPDATE SET summary = excluded.summary, updated_at = CURRENT_TIMESTAMP
                """,
                (chat_id, summary),
            )

    def get_conversation_summary(self, chat_id: int) -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT summary FROM conversation_summary WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            return str(row["summary"]) if row else ""


def _decode_messages(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    messages = []
    for row in rows:
        item = dict(row)
        item["citations"] = json.loads(item.pop("citations_json") or "[]")
        messages.append(item)
    return messages


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
