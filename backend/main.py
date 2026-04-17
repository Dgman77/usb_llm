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


# ── Startup: load model before first request ───────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[Server] USB root : {USB_ROOT}")
    print(f"[Server] Frontend : {FRONTEND_DIR}")
    try:
        load_model()
        print("[Server] Ready — http://localhost:8787")
    except FileNotFoundError as e:
        print(str(e))
        print("[Server] WARNING: No model loaded. /api/generate will fail.")
    yield
    print("[Server] Stopped.")


app = FastAPI(title="DiagramAI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend files (index.html + mermaid.min.js) — 100% offline
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ── Routes ─────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


class GenerateRequest(BaseModel):
    message: str


@app.post("/api/generate")
async def api_generate(req: GenerateRequest):
    if not req.message.strip():
        raise HTTPException(400, "Message cannot be empty")

    try:
        result = handle_request(req.message)
    except FileNotFoundError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"Generation failed: {e}")

    return JSONResponse(result)


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".pdf", ".docx", ".txt")):
        raise HTTPException(400, "Only PDF, DOCX, or TXT files supported")
    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 50MB)")
    try:
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


@app.get("/api/status")
async def api_status():
    return JSONResponse({"server": "ok", "rag": get_stats()})


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8787, reload=False)
