from __future__ import annotations

import json
from pathlib import Path
from typing import Any, BinaryIO

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from research_copilot.comparison import compare_documents
from research_copilot.exports import export_chat_docx, export_chat_markdown, export_chat_pdf
from research_copilot.pdf_ingestion import ingest_pdf
from research_copilot.pdf_ingestion import reprocess_document
from research_copilot.service_factory import get_services


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"


class NamedFile:
    def __init__(self, file: BinaryIO, name: str):
        self.file = file
        self.name = name

    def read(self, size: int = -1) -> bytes:
        return self.file.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.file.seek(offset, whence)


def json_line(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8")


async def home(_request: Request) -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


async def health(_request: Request) -> JSONResponse:
    services = get_services()
    return JSONResponse(
        {
            "status": "ok",
            "embedding": services.embedder.status,
            "reranker": services.settings.reranker_enabled,
            "ollama_model": services.settings.ollama_model,
        }
    )


async def bootstrap(_request: Request) -> JSONResponse:
    services = get_services()
    db = services.db
    workspace_id = db.ensure_workspace("Default Workspace")
    chat_id = db.ensure_chat(workspace_id, "Research Chat")
    return JSONResponse(
        {
            "settings": {
                "embedding": services.embedder.status,
                "reranker": services.settings.reranker_enabled,
                "ollama_model": services.settings.ollama_model,
                "chat_history_limit": services.settings.chat_history_limit,
            },
            "workspaces": db.list_workspaces(),
            "workspace_id": workspace_id,
            "chats": db.list_chats(workspace_id),
            "chat_id": chat_id,
        }
    )


async def list_workspaces(_request: Request) -> JSONResponse:
    return JSONResponse({"workspaces": get_services().db.list_workspaces()})


async def create_workspace(request: Request) -> JSONResponse:
    payload = await request.json()
    name = str(payload.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "Workspace name is required."}, status_code=400)
    workspace_id = await run_in_threadpool(get_services().db.create_workspace, name)
    return JSONResponse({"workspace_id": workspace_id})


async def list_chats(request: Request) -> JSONResponse:
    workspace_id = int(request.query_params.get("workspace_id", "0"))
    chats = await run_in_threadpool(get_services().db.list_chats, workspace_id)
    return JSONResponse({"chats": chats})


async def create_chat(request: Request) -> JSONResponse:
    payload = await request.json()
    workspace_id = int(payload.get("workspace_id") or 0)
    title = str(payload.get("title") or "Research Chat").strip() or "Research Chat"
    chat_id = await run_in_threadpool(get_services().db.create_chat, workspace_id, title)
    return JSONResponse({"chat_id": chat_id})


async def messages(request: Request) -> JSONResponse:
    services = get_services()
    chat_id = int(request.query_params.get("chat_id", "0"))
    limit = int(request.query_params.get("limit", str(services.settings.chat_history_limit)))
    total = await run_in_threadpool(services.db.count_messages, chat_id)
    recent = await run_in_threadpool(services.db.get_recent_messages, chat_id, limit)
    return JSONResponse({"messages": recent, "total": total, "limit": limit})


async def stream_chat(request: Request) -> StreamingResponse:
    payload = await request.json()
    services = get_services()
    workspace_id = int(payload.get("workspace_id") or 0)
    chat_id = int(payload.get("chat_id") or 0)
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return StreamingResponse(iter([json_line({"type": "error", "message": "Prompt is required."})]))

    def generate():
        services.db.add_message(chat_id, "user", prompt)
        yield json_line({"type": "status", "message": "Retrieving local sources..."})
        prepared = services.rag.prepare_answer(workspace_id, chat_id, prompt)
        yield json_line({"type": "status", "message": "Writing answer..."})
        chunks: list[str] = []
        for piece in services.rag.stream_prepared(prepared):
            chunks.append(piece)
            yield json_line({"type": "delta", "text": piece})
        content = "".join(chunks)
        services.db.add_message(chat_id, "assistant", content, prepared.citations)
        services.db.update_conversation_summary(chat_id)
        yield json_line(
            {
                "type": "done",
                "content": content,
                "citations": prepared.citations,
            }
        )

    return StreamingResponse(generate(), media_type="application/x-ndjson")


async def documents(request: Request) -> JSONResponse:
    workspace_id = int(request.query_params.get("workspace_id", "0"))
    docs = await run_in_threadpool(get_services().db.list_documents, workspace_id)
    return JSONResponse({"documents": docs})


async def document_pdf(request: Request) -> FileResponse | JSONResponse:
    document_id = int(request.path_params["document_id"])
    document = await run_in_threadpool(get_services().db.get_document, document_id)
    if not document:
        return JSONResponse({"error": "Document not found."}, status_code=404)
    path = Path(document["file_path"])
    if not path.exists():
        return JSONResponse({"error": "PDF file is missing on disk."}, status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=document["file_name"])


async def upload_pdf(request: Request) -> JSONResponse:
    services = get_services()
    form = await request.form()
    workspace_id = int(form.get("workspace_id") or 0)
    chat_id = int(form.get("chat_id") or 0)
    upload = form.get("file")
    if upload is None or not hasattr(upload, "file"):
        return JSONResponse({"error": "PDF file is required."}, status_code=400)
    named_file = NamedFile(upload.file, upload.filename or "document.pdf")
    result = await run_in_threadpool(
        ingest_pdf,
        services.settings,
        services.db,
        services.embedder,
        services.vector_store,
        workspace_id,
        chat_id,
        named_file,
    )
    return JSONResponse(
        {
            "document_id": result.document_id,
            "chunk_count": result.chunk_count,
            "is_duplicate": result.is_duplicate,
            "page_count": result.page_count,
            "status": result.status,
            "message": result.message,
        }
    )


async def reprocess_pdf(request: Request) -> JSONResponse:
    services = get_services()
    document_id = int(request.path_params["document_id"])
    result = await run_in_threadpool(
        reprocess_document,
        services.settings,
        services.db,
        services.embedder,
        services.vector_store,
        document_id,
    )
    return JSONResponse(
        {
            "document_id": result.document_id,
            "chunk_count": result.chunk_count,
            "page_count": result.page_count,
            "status": result.status,
            "message": result.message,
        }
    )


async def delete_pdf(request: Request) -> JSONResponse:
    services = get_services()
    document_id = int(request.path_params["document_id"])

    def _do_delete():
        services.vector_store.delete_chunks_for_document(document_id)
        services.db.delete_document(document_id)

    await run_in_threadpool(_do_delete)
    return JSONResponse({"status": "deleted"})

async def notes(request: Request) -> JSONResponse:
    services = get_services()
    if request.method == "GET":
        workspace_id = int(request.query_params.get("workspace_id", "0"))
        chat_id = int(request.query_params.get("chat_id", "0"))
        items = await run_in_threadpool(services.db.list_notes, workspace_id, chat_id)
        return JSONResponse({"notes": items})

    payload = await request.json()
    workspace_id = int(payload.get("workspace_id") or 0)
    chat_id = int(payload.get("chat_id") or 0)
    title = str(payload.get("title") or "Untitled note").strip() or "Untitled note"
    body = str(payload.get("body") or "").strip()
    note_id = await run_in_threadpool(services.db.add_note, workspace_id, chat_id, title, body)
    return JSONResponse({"note_id": note_id})


async def graph(request: Request) -> JSONResponse:
    services = get_services()
    workspace_id = int(request.query_params.get("workspace_id", "0"))
    regenerate = request.query_params.get("regenerate") == "1"
    if regenerate:
        await run_in_threadpool(services.graph_builder.rebuild_workspace, workspace_id)
    path = await run_in_threadpool(services.graph_builder.render_workspace, workspace_id)
    if not path:
        return JSONResponse({"html": "", "empty": True})
    return JSONResponse({"html": Path(path).read_text(encoding="utf-8"), "empty": False})


async def compare(request: Request) -> JSONResponse:
    payload = await request.json()
    doc_a = int(payload.get("document_a_id") or 0)
    doc_b = int(payload.get("document_b_id") or 0)
    result = await run_in_threadpool(compare_documents, get_services().db, doc_a, doc_b)
    return JSONResponse({"markdown": result})


async def literature_review(request: Request) -> JSONResponse:
    payload = await request.json()
    services = get_services()
    workspace_id = int(payload.get("workspace_id") or 0)
    chat_id = int(payload.get("chat_id") or 0)
    answer = await run_in_threadpool(services.rag.literature_review, workspace_id, chat_id)
    return JSONResponse({"content": answer.content, "citations": answer.citations})


async def export_chat(request: Request) -> JSONResponse:
    services = get_services()
    kind = request.path_params["kind"]
    chat_id = int(request.query_params.get("chat_id", "0"))
    exporters = {
        "markdown": export_chat_markdown,
        "docx": export_chat_docx,
        "pdf": export_chat_pdf,
    }
    exporter = exporters.get(kind)
    if exporter is None:
        return JSONResponse({"error": "Unknown export type."}, status_code=404)
    path = await run_in_threadpool(exporter, services.settings, services.db, chat_id)
    return JSONResponse({"path": str(path)})


async def not_found(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("Not found", status_code=404)


routes = [
    Route("/", home),
    Route("/api/health", health),
    Route("/api/bootstrap", bootstrap),
    Route("/api/workspaces", list_workspaces, methods=["GET"]),
    Route("/api/workspaces", create_workspace, methods=["POST"]),
    Route("/api/chats", list_chats, methods=["GET"]),
    Route("/api/chats", create_chat, methods=["POST"]),
    Route("/api/messages", messages, methods=["GET"]),
    Route("/api/chat", stream_chat, methods=["POST"]),
    Route("/api/documents", documents, methods=["GET"]),
    Route("/api/documents/{document_id:int}/pdf", document_pdf, methods=["GET"]),
    Route("/api/documents/{document_id:int}/reprocess", reprocess_pdf, methods=["POST"]),
    Route("/api/documents/{document_id:int}", delete_pdf, methods=["DELETE"]),
    Route("/api/upload", upload_pdf, methods=["POST"]),
    Route("/api/notes", notes, methods=["GET", "POST"]),
    Route("/api/graph", graph, methods=["GET"]),
    Route("/api/compare", compare, methods=["POST"]),
    Route("/api/literature-review", literature_review, methods=["POST"]),
    Route("/api/export/{kind}", export_chat, methods=["POST"]),
    Mount("/web", StaticFiles(directory=WEB_DIR), name="web"),
]


app = Starlette(routes=routes)
