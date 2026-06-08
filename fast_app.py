from __future__ import annotations

import base64
import json
import re
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse, Response
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


async def list_models(request: Request) -> JSONResponse:
    services = get_services()
    try:
        import ollama
        client = ollama.Client(host=services.settings.ollama_host)
        resp = client.list()
        # Handle both dict and object responses from different ollama versions
        models_list = []
        if hasattr(resp, "get"):
            models_list = resp.get("models") or getattr(resp, "models", [])
        else:
            models_list = getattr(resp, "models", [])
            
        models = []
        for m in models_list:
            if isinstance(m, dict):
                name = m.get("model") or m.get("name")
            else:
                name = getattr(m, "model", None) or getattr(m, "name", None)
            if name:
                models.append(str(name))
                
        if not models:
            models = [services.rag.llm.model]
    except Exception as e:
        print(f"Error fetching models: {e}")
        models = [services.rag.llm.model]
    
    return JSONResponse({
        "models": models,
        "active": services.rag.llm.model
    })


async def select_model(request: Request) -> JSONResponse:
    services = get_services()
    payload = await request.json()
    new_model = payload.get("model")
    if new_model:
        # In-memory override for the current session
        object.__setattr__(services.rag.llm, "model", new_model)
    return JSONResponse({"status": "success", "active": services.rag.llm.model})


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
    image_ids = payload.get("image_ids") or []
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt and not image_ids:
        return StreamingResponse(iter([json_line({"type": "error", "message": "Prompt or image is required."})]))

    def generate():
        services.db.add_message(chat_id, "user", prompt)
        
        b64_images = []
        if image_ids:
            for i_id in image_ids:
                image_record = services.db.get_image(i_id)
                if image_record:
                    path = Path(image_record["file_path"])
                    if path.exists():
                        with open(path, "rb") as img_file:
                            b64_images.append(base64.b64encode(img_file.read()).decode("utf-8"))
        
        yield json_line({"type": "status", "message": "Retrieving local sources..."})
        prepared = services.rag.prepare_answer(workspace_id, chat_id, prompt, b64_images)
        yield json_line({"type": "status", "message": "Writing answer..."})
        chunks: list[str] = []
        for piece in services.rag.stream_prepared(prepared):
            chunks.append(piece)
            yield json_line({"type": "delta", "text": piece})
        content = "".join(chunks)
        
        used_numbers = set()
        for bracket_match in re.finditer(r'\[(.*?)\]', content):
            inner_text = bracket_match.group(1)
            for num_match in re.finditer(r'\d+', inner_text):
                used_numbers.add(int(num_match.group(0)))
                
        filtered_citations = [c for c in prepared.citations if c["number"] in used_numbers]
        
        message_id = services.db.add_message(chat_id, "assistant", content, filtered_citations)
        if image_ids:
            for i_id in image_ids:
                services.db.link_image_to_message(i_id, message_id)
            
        services.db.update_conversation_summary(chat_id)
        yield json_line(
            {
                "type": "done",
                "content": content,
                "citations": filtered_citations,
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
    return FileResponse(
        path, 
        media_type="application/pdf", 
        headers={"Content-Disposition": "inline"}
    )

async def document_highlight(request: Request) -> Response | JSONResponse:
    document_id = int(request.path_params["document_id"])
    chunk_id = int(request.path_params["chunk_id"])
    services = get_services()
    
    document = await run_in_threadpool(services.db.get_document, document_id)
    if not document:
        return JSONResponse({"error": "Document not found."}, status_code=404)
        
    chunk = await run_in_threadpool(services.db.get_chunk, chunk_id)
    if not chunk or chunk["document_id"] != document_id:
        return JSONResponse({"error": "Chunk not found."}, status_code=404)
        
    path = Path(document["file_path"])
    if not path.exists():
        return JSONResponse({"error": "PDF file is missing on disk."}, status_code=404)
        
    def highlight_pdf():
        import fitz
        doc = fitz.open(path)
        # page_start is 1-indexed in database, PyMuPDF is 0-indexed
        page_idx = (chunk["page_start"] - 1) if chunk.get("page_start") else 0
        if page_idx < 0 or page_idx >= doc.page_count:
            page_idx = 0
            
        page = doc[page_idx]
        import re
        clean_text = re.sub(r'\s+', ' ', chunk["text"]).strip()
        
        # 1. Try to search the whole cleaned text
        rects = page.search_for(clean_text)
        found_any = False
        if rects:
            for rect in rects:
                annot = page.add_highlight_annot(rect)
                if annot: annot.update()
            found_any = True
            
        if not found_any:
            # 2. Try by sentences
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', clean_text) if len(s.strip()) > 20]
            for sentence in sentences:
                s_rects = page.search_for(sentence)
                if s_rects:
                    found_any = True
                    for rect in s_rects:
                        annot = page.add_highlight_annot(rect)
                        if annot: annot.update()
                        
        if not found_any:
            # 3. Fallback to 8-word sliding window to avoid random short highlights
            words = clean_text.split()
            if len(words) > 8:
                for i in range(0, len(words) - 7, 5):
                    phrase = " ".join(words[i:i+8])
                    p_rects = page.search_for(phrase)
                    for rect in p_rects:
                        annot = page.add_highlight_annot(rect)
                        if annot: annot.update()
            else:
                for rect in page.search_for(clean_text):
                    annot = page.add_highlight_annot(rect)
                    if annot: annot.update()

        return doc.tobytes()
        
    pdf_bytes = await run_in_threadpool(highlight_pdf)
    return Response(content=pdf_bytes, media_type="application/pdf")


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
    if result.chunk_count > 0:
        await run_in_threadpool(services.graph_builder.build_for_document, result.document_id)
        await run_in_threadpool(services.graph_builder.render_workspace, workspace_id)
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


async def upload_image(request: Request) -> JSONResponse:
    services = get_services()
    form = await request.form()
    workspace_id = int(form.get("workspace_id") or 0)
    chat_id = int(form.get("chat_id") or 0)
    upload = form.get("file")
    if upload is None or not hasattr(upload, "file"):
        return JSONResponse({"error": "Image file is required."}, status_code=400)
    
    images_dir = services.settings.uploads_dir / str(workspace_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    
    filename = upload.filename or "image.png"
    ext = filename.split(".")[-1] if "." in filename else "png"
    file_path = images_dir / f"{uuid.uuid4().hex}.{ext}"
    
    with open(file_path, "wb") as buffer:
        buffer.write(upload.file.read())
        
    image_id = await run_in_threadpool(
        services.db.add_image,
        workspace_id, chat_id, filename, str(file_path), upload.content_type or "image/png"
    )
    return JSONResponse({"image_id": image_id})


async def get_images(request: Request) -> JSONResponse:
    workspace_id = int(request.query_params.get("workspace_id", "0"))
    images = await run_in_threadpool(get_services().db.list_images, workspace_id)
    return JSONResponse({"images": images})


async def get_image_content(request: Request) -> FileResponse | JSONResponse:
    image_id = int(request.path_params["image_id"])
    image = await run_in_threadpool(get_services().db.get_image, image_id)
    if not image:
        return JSONResponse({"error": "Image not found."}, status_code=404)
    path = Path(image["file_path"])
    if not path.exists():
        return JSONResponse({"error": "Image file is missing on disk."}, status_code=404)
    return FileResponse(path, media_type=image["mime_type"])


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
    if result.chunk_count > 0:
        await run_in_threadpool(services.graph_builder.build_for_document, result.document_id)
        document = await run_in_threadpool(services.db.get_document, document_id)
        if document:
            await run_in_threadpool(services.graph_builder.render_workspace, int(document["workspace_id"]))
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
    return FileResponse(path, filename=path.name, content_disposition_type="attachment")


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
    Route("/api/models", list_models, methods=["GET"]),
    Route("/api/models/select", select_model, methods=["POST"]),
    Route("/api/messages", messages, methods=["GET"]),
    Route("/api/chat", stream_chat, methods=["POST"]),
    Route("/api/documents", documents, methods=["GET"]),
    Route("/api/documents/{document_id:int}/pdf", document_pdf, methods=["GET"]),
    Route("/api/documents/{document_id:int}/highlight/{chunk_id:int}", document_highlight, methods=["GET"]),
    Route("/api/documents/{document_id:int}/reprocess", reprocess_pdf, methods=["POST"]),
    Route("/api/documents/{document_id:int}", delete_pdf, methods=["DELETE"]),
    Route("/api/upload", upload_pdf, methods=["POST"]),
    Route("/api/upload_image", upload_image, methods=["POST"]),
    Route("/api/images", get_images, methods=["GET"]),
    Route("/api/images/{image_id:int}/content", get_image_content, methods=["GET"]),
    Route("/api/notes", notes, methods=["GET", "POST"]),
    Route("/api/graph", graph, methods=["GET"]),
    Route("/api/compare", compare, methods=["POST"]),
    Route("/api/literature-review", literature_review, methods=["POST"]),
    Route("/api/export/{kind}", export_chat, methods=["POST"]),
    Mount("/web", StaticFiles(directory=WEB_DIR), name="web"),
]


app = Starlette(routes=routes)
