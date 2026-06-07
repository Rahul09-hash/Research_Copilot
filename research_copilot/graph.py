from __future__ import annotations

import html
import itertools
import re
from pathlib import Path

import networkx as nx

from research_copilot.config import Settings
from research_copilot.database import Database


ENTITY_PATTERN = re.compile(
    r"\b(?:[A-Z][a-zA-Z0-9-]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-zA-Z0-9-]+|[A-Z]{2,})){0,4}\b"
)
STOP_ENTITIES = {
    "Abstract",
    "Introduction",
    "Conclusion",
    "References",
    "Figure",
    "Table",
    "Copyright",
}


class KnowledgeGraphBuilder:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    def build_for_document(self, document_id: int) -> None:
        document = self.db.get_document(document_id)
        if not document:
            return
        chunks = self.db.get_chunks_for_document(document_id)
        
        with self.db.connect() as conn:
            for chunk in chunks:
                names = extract_entities(chunk["text"])
                entity_ids = []
                for name in names:
                    normalized = name.strip()
                    conn.execute(
                        "INSERT OR IGNORE INTO entity(workspace_id, name, type) VALUES (?, ?, ?)",
                        (document["workspace_id"], normalized, "concept"),
                    )
                    row = conn.execute(
                        "SELECT id FROM entity WHERE workspace_id = ? AND name = ?",
                        (document["workspace_id"], normalized),
                    ).fetchone()
                    entity_ids.append(int(row["id"]))
                    
                for source_id, target_id in itertools.combinations(entity_ids[:8], 2):
                    if source_id == target_id: continue
                    if source_id > target_id: source_id, target_id = target_id, source_id
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
                        (document["workspace_id"], source_id, target_id, "co_occurs", document_id, chunk["id"]),
                    )

    def rebuild_workspace(self, workspace_id: int) -> None:
        self.db.clear_graph(workspace_id)
        for document in self.db.list_documents(workspace_id):
            self.build_for_document(document["id"])

    def render_workspace(self, workspace_id: int) -> str | None:
        entities, relationships = self.db.list_graph(workspace_id)
        if not entities:
            return None
        graph_path = self.settings.graphs_dir / f"workspace_{workspace_id}.html"
        try:
            from pyvis.network import Network

            network = Network(height="620px", width="100%", bgcolor="#ffffff", font_color="#222222")
            network.barnes_hut()
            for entity in entities:
                network.add_node(entity["id"], label=entity["name"], title=entity["type"])
            for relationship in relationships:
                network.add_edge(
                    relationship["source_entity_id"],
                    relationship["target_entity_id"],
                    value=max(1.0, float(relationship["weight"])),
                    title=relationship["label"],
                )
            network.write_html(str(graph_path), open_browser=False, notebook=False)
        except Exception:
            graph_path.write_text(_fallback_html(entities, relationships), encoding="utf-8")
        return str(graph_path)


def extract_entities(text: str, limit: int = 20) -> list[str]:
    seen: set[str] = set()
    entities: list[str] = []
    for match in ENTITY_PATTERN.findall(text):
        name = " ".join(match.split()).strip()
        if len(name) < 3 or name in STOP_ENTITIES or name in seen:
            continue
        seen.add(name)
        entities.append(name)
        if len(entities) >= limit:
            break
    return entities


def _fallback_html(entities: list[dict], relationships: list[dict]) -> str:
    graph = nx.Graph()
    for entity in entities:
        graph.add_node(entity["name"])
    for relationship in relationships:
        graph.add_edge(relationship["source_name"], relationship["target_name"], weight=relationship["weight"])
    rows = []
    for source, target, data in graph.edges(data=True):
        rows.append(
            "<tr>"
            f"<td>{html.escape(source)}</td>"
            f"<td>{html.escape(target)}</td>"
            f"<td>{html.escape(str(data.get('weight', 1)))}</td>"
            "</tr>"
        )
    return (
        "<html><body><h3>Knowledge Graph</h3>"
        "<table border='1' cellpadding='6' cellspacing='0'>"
        "<tr><th>Source</th><th>Target</th><th>Weight</th></tr>"
        + "\n".join(rows)
        + "</table></body></html>"
    )
