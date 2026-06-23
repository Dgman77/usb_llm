"""
main.py — FastAPI web server.

Paths are derived from THIS FILE's location so the app works
on any drive letter (D: E: G: etc.)
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from router import route, detect_diagram_type
from llm import load_model, generate
from rag import add_document, remove_document, search, get_stats
from orchestrator import handle_request


# USB-safe paths — always relative to this file's location
USB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(USB_ROOT, "frontend")

UPLOADS_DIR = os.path.join(USB_ROOT, "data", "uploads")
IMAGES_DIR = os.path.join(USB_ROOT, "data", "images")
EXPORTS_DIR = os.path.join(USB_ROOT, "data", "exports")
DIAGRAMS_DIR = os.path.join(USB_ROOT, "data", "diagrams")
JS_DIR = os.path.join(USB_ROOT, "js")


# ── Startup: load model before first request ───────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[Server] USB root : {USB_ROOT}")
    print(f"[Server] Frontend : {FRONTEND_DIR}")
    
    # FIX-13: Create storage folders on startup
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    os.makedirs(DIAGRAMS_DIR, exist_ok=True)
    print("Storage ready: data/uploads | data/images | data/exports | data/diagrams")
    
    try:
        # FIX-1: Load all 3 resident models
        from llm import load_all_models
        load_all_models()
        
        # FIX-4: Load persisted FAISS index
        from rag import load_persisted_index
        load_persisted_index()
        
        print("[Server] Ready — http://localhost:8787")
    except FileNotFoundError as e:
        print(str(e))
        print("[Server] WARNING: No model loaded. /api/generate will fail.")
    except Exception as e:
        print(f"[Server] WARNING: Model loading error: {e}")
        print("[Server] Server will start but model loading is deferred.")
    yield
    print("[Server] Stopping...")
    try:
        from llm import unload_chat_model, unload_embed_model, unload_reranker
        unload_chat_model()
        unload_embed_model()
        unload_reranker()
    except Exception as e:
        print(f"[Server] Error during shutdown unloads: {e}")
    print("[Server] Stopped.")


app = FastAPI(title="Flash AI with RAG ", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8787",
        "http://127.0.0.1:8787"
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend files (index.html + assets) — 100% offline
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
# Serve JS files (viz-standalone.js) — 100% offline
app.mount("/js", StaticFiles(directory=JS_DIR), name="js")


# ── Routes ─────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


class GenerateRequest(BaseModel):
    message: str


import asyncio
_generate_lock = asyncio.Semaphore(1)


@app.post("/api/generate")
async def api_generate(req: GenerateRequest):
    if not req.message.strip():
        raise HTTPException(400, "Message cannot be empty")

    if not _generate_lock.locked():
        async with _generate_lock:
            try:
                result = handle_request(req.message)
            except FileNotFoundError as e:
                raise HTTPException(503, str(e))
            except Exception as e:
                raise HTTPException(500, f"Generation failed: {e}")
            return JSONResponse(result)
    else:
        return JSONResponse(
            status_code=429,
            content={
                "error": "Generation in progress. Please wait."
            }
        )


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    supported = (
        ".pdf", ".docx", ".txt", ".csv", ".xlsx", ".pptx", ".html", ".htm",
        ".md", ".json", ".xml", ".rtf", ".log", ".py", ".js", ".ts", ".css",
        ".yaml", ".yml", ".ini", ".cfg", ".toml",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"
    )
    if not file.filename.lower().endswith(supported):
        raise HTTPException(400, f"Unsupported file type. Supported: {', '.join(supported)}")
    
    contents = await file.read()
    if len(contents) > 100 * 1024 * 1024:  # Increased to 100MB for larger docs/images
        raise HTTPException(400, "File too large (max 100MB)")
        
    ext = os.path.splitext(file.filename.lower())[1]
    is_image = ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp")
    
    try:
        if is_image:
            dest_path = os.path.join(IMAGES_DIR, file.filename)
            with open(dest_path, "wb") as f:
                f.write(contents)
            n = 0
        else:
            dest_path = os.path.join(UPLOADS_DIR, file.filename)
            with open(dest_path, "wb") as f:
                f.write(contents)
            n = add_document(contents, file.filename)
    except Exception as e:
        raise HTTPException(500, f"Failed to process file: {e}")
    return JSONResponse({"filename": file.filename, "chunks_added": n})


@app.post("/api/remove")
async def api_remove(req: dict):
    filename = req.get("filename")
    if not filename:
        raise HTTPException(400, "Filename required")
    removed = remove_document(filename)
    if not removed:
        raise HTTPException(404, "Document not found")
    return JSONResponse({"filename": filename, "removed": True})


@app.get("/api/models")
async def api_get_models():
    from llm import find_available_models, get_model_name
    models = find_available_models()
    # Filter out embed and reranker models (FIX-14)
    filtered = []
    for m in models:
        name_lower = m["name"].lower()
        if any(term in name_lower for term in ("embed", "rerank", "bge-reranker", "nomic")):
            continue
        filtered.append(m)
    return JSONResponse({
        "models": filtered,
        "active": get_model_name()
    })


class SwitchRequest(BaseModel):
    path: str


@app.post("/api/models/switch")
async def api_switch_model(req: SwitchRequest):
    from llm import switch_model
    if not os.path.exists(req.path):
        raise HTTPException(404, f"Model file not found: {req.path}")
    try:
        res = switch_model(req.path)
        if not res.get("success", False):
            return JSONResponse(status_code=400, content=res)
        return JSONResponse(res)
    except Exception as e:
        raise HTTPException(500, f"Failed to switch model: {e}")


@app.get("/api/status")
async def api_status():
    from llm import get_model_name, CURRENT_STRATEGY
    return JSONResponse({
        "server": "ok",
        "active_model": get_model_name(),
        "strategy": CURRENT_STRATEGY,
        "rag": get_stats()
    })


class SaveDiagramRequest(BaseModel):
    dot_code: str
    name: str = ""


@app.post("/api/save-diagram")
async def api_save_diagram(req: SaveDiagramRequest):
    """Auto-save a DOT diagram to the diagrams output folder."""
    import time
    name = req.name.strip() or f"diagram_{int(time.time())}"
    # Sanitize filename
    safe_name = re.sub(r'[^\w\-.]', '_', name)
    if not safe_name.endswith('.dot'):
        safe_name += '.dot'
    filepath = os.path.join(DIAGRAMS_DIR, safe_name)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(req.dot_code)
    return JSONResponse({"saved": True, "filename": safe_name, "path": filepath})



# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8787, reload=False)
