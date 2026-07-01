"""
rag.py — Dense RAG with multi-format + image support
Supports: PDF, DOCX, TXT, CSV, XLSX, PPTX, HTML, MD, JSON, XML, RTF, Images

Search: Dense vector search via FAISS IndexFlatIP
        with cosine similarity (L2 normalisation).

Persistence: SQLite metadata.db (Python built-in sqlite3, zero extra deps).
             Eliminates chunks_meta.json write amplification on USB drives.
"""

import os
import re
import io
import csv
import json
import base64
import sqlite3
import html as html_mod
import xml.etree.ElementTree as ET
import numpy as np

import faiss
import fitz                           # PDF + images → PyMuPDF
from docx import Document as DocxDoc  # DOCX → python-docx

# ── Optional imports (graceful fallback) ──────────────────
try:
    import openpyxl
    _HAS_XLSX = True
except ImportError:
    _HAS_XLSX = False

try:
    from pptx import Presentation
    _HAS_PPTX = True
except ImportError:
    _HAS_PPTX = False

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

try:
    from striprtf.striprtf import rtf_to_text
    _HAS_RTF = True
except ImportError:
    _HAS_RTF = False

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


# ── State (in-memory only) ────────────────────────────────
_chunks = []
_parent_chunks = []
_chunk_doc = []
_chunk_page = []
_chunk_type = []        # "text" | "image_meta"
_doc_names = []
_images = {}            # doc_name → [{data, ext, page, desc}, ...]
_faiss_index = None

# NOTE: _embeddings list removed — embeddings live in FAISS index only.
# This reduces in-memory overhead significantly on low-spec devices.

# USB-safe root path for persistence
USB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(USB_ROOT, "metadata.db")
_INDEX_PATH = os.path.join(USB_ROOT, "index.faiss")


# ── SQLite helpers ────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    """Open (or create) the metadata SQLite database."""
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")   # Write-Ahead Log — safer on USB
    conn.execute("PRAGMA synchronous=NORMAL") # Balance safety / write speed
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            text        TEXT    NOT NULL,
            parent_text TEXT    NOT NULL,
            doc         TEXT    NOT NULL,
            page        INTEGER NOT NULL DEFAULT 1,
            chunk_type  TEXT    NOT NULL DEFAULT 'text'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_names (
            name TEXT PRIMARY KEY
        )
    """)
    conn.commit()
    return conn


def _load_metadata_from_db():
    """Load chunk metadata from SQLite into memory lists."""
    global _chunks, _parent_chunks, _chunk_doc, _chunk_page, _chunk_type, _doc_names
    _chunks.clear()
    _parent_chunks.clear()
    _chunk_doc.clear()
    _chunk_page.clear()
    _chunk_type.clear()
    _doc_names.clear()

    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT text, parent_text, doc, page, chunk_type FROM chunks ORDER BY id"
        ).fetchall()
        for text, parent_text, doc, page, chunk_type in rows:
            _chunks.append(text)
            _parent_chunks.append(parent_text)
            _chunk_doc.append(doc)
            _chunk_page.append(page)
            _chunk_type.append(chunk_type)

        doc_rows = conn.execute("SELECT name FROM doc_names").fetchall()
        _doc_names.extend(row[0] for row in doc_rows)
        conn.close()
        print(f"[RAG] Loaded {len(_chunks)} chunks from metadata.db")
    except Exception as e:
        print(f"[RAG] WARNING: Failed to load metadata from db: {e}")


def _save_chunks_to_db(new_chunks, new_parents, new_docs, new_pages, new_types, doc_name):
    """Append new chunk rows and register the document name in SQLite."""
    try:
        conn = _get_db()
        conn.executemany(
            "INSERT INTO chunks (text, parent_text, doc, page, chunk_type) VALUES (?,?,?,?,?)",
            zip(new_chunks, new_parents, new_docs, new_pages, new_types),
        )
        conn.execute(
            "INSERT OR IGNORE INTO doc_names (name) VALUES (?)", (doc_name,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[RAG] WARNING: Failed to save chunks to db: {e}")


def _delete_doc_from_db(filename: str):
    """Remove all rows for a document from the SQLite database."""
    try:
        conn = _get_db()
        conn.execute("DELETE FROM chunks WHERE doc = ?", (filename,))
        conn.execute("DELETE FROM doc_names WHERE name = ?", (filename,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[RAG] WARNING: Failed to delete doc from db: {e}")


def _clear_db():
    """Drop all rows from both tables."""
    try:
        conn = _get_db()
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM doc_names")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[RAG] WARNING: Failed to clear db: {e}")


# ── Chunking by Tokens ────────────────────────────────────
def chunk_text_by_tokens(text: str, model, chunk_size: int, overlap: int) -> list[str]:
    """Split text into sentence-aware chunks of specified tokens with overlap."""
    # Split text into sentences/paragraphs using regex
    sentences = re.split(r'(?<=[.!?])\s+|\n+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return []

    chunks = []
    current_chunk = []
    current_tokens = 0

    for sentence in sentences:
        try:
            s_tokens = len(model.tokenize(sentence.encode('utf-8', errors='ignore')))
        except Exception:
            s_tokens = len(sentence.split())  # fallback
            
        if current_tokens + s_tokens > chunk_size and current_chunk:
            chunks.append(" ".join(current_chunk))
            # Build overlap by taking sentences from the end of the current chunk
            overlap_chunk = []
            overlap_tokens = 0
            for s in reversed(current_chunk):
                try:
                    s_tok = len(model.tokenize(s.encode('utf-8', errors='ignore')))
                except Exception:
                    s_tok = len(s.split())
                if overlap_tokens + s_tok > overlap:
                    break
                overlap_chunk.insert(0, s)
                overlap_tokens += s_tok
            current_chunk = overlap_chunk
            current_tokens = overlap_tokens

        current_chunk.append(sentence)
        current_tokens += s_tokens

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks if chunks else [text]


# ── Build FAISS Index ─────────────────────────────────────
def _rebuild(embeddings: list):
    """Rebuild the FAISS index from a list of embedding vectors."""
    global _faiss_index
    if not embeddings:
        _faiss_index = None
        return

    dim = len(embeddings[0])
    mat = np.array(embeddings, dtype="float32")

    # Normalize each vector for Cosine Similarity (via Inner Product Flat index)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    mat = mat / norms

    _faiss_index = faiss.IndexFlatIP(dim)
    _faiss_index.add(mat)
    print(f"[RAG] FAISS Index rebuilt with {len(embeddings)} chunks (dim={dim})")


# ═══════════════════════════════════════════════════════════
#  EXTRACTORS — each returns (pages, images)
#  pages  = [(page_num, text), ...]
#  images = [{data, ext, page, desc}, ...]   (may be empty)
# ═══════════════════════════════════════════════════════════

def _wrap_pages(pages):
    """Helper: return (pages, []) for extractors that have no images."""
    return pages, []


def extract_pdf(fb: bytes):
    doc = fitz.open(stream=fb, filetype="pdf")
    pages = [(i + 1, p.get_text()) for i, p in enumerate(doc)]
    images = []
    for i, page in enumerate(doc):
        for idx, img in enumerate(page.get_images(full=True)):
            try:
                bi = doc.extract_image(img[0])
                if bi:
                    images.append({
                        "data": bi["image"], "ext": bi["ext"], "page": i + 1,
                        "desc": f"Image {idx+1} page {i+1} ({bi.get('width',0)}x{bi.get('height',0)} {bi['ext']})"
                    })
            except Exception:
                pass
    return pages, images


def extract_docx(fb: bytes):
    doc = DocxDoc(io.BytesIO(fb))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    pages, buf, pn = [], "", 1
    for para in paragraphs:
        if len(buf) + len(para) > 1500:
            pages.append((pn, buf.strip())); buf = para + "\n"; pn += 1
        else:
            buf += para + "\n"
    if buf.strip():
        pages.append((pn, buf.strip()))
    images = []
    try:
        for rel in doc.part.rels.values():
            if "image" in rel.reltype:
                ext = os.path.splitext(rel.target_part.partname)[1].lstrip(".")
                images.append({"data": rel.target_part.blob, "ext": ext, "page": 1,
                               "desc": f"Embedded image ({ext})"})
    except Exception:
        pass
    return pages, images


def extract_txt(fb: bytes):
    text = fb.decode("utf-8", errors="replace")
    lines = text.splitlines()
    pages, buf, pn = [], "", 1
    for line in lines:
        if len(buf) + len(line) > 1500:
            pages.append((pn, buf.strip())); buf = line + "\n"; pn += 1
        else:
            buf += line + "\n"
    if buf.strip():
        pages.append((pn, buf.strip()))
    return _wrap_pages(pages)


def extract_csv(fb: bytes):
    text = fb.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return _wrap_pages([])
    buf, pn, pages = "", 1, []
    for row in rows:
        line = " | ".join(row)
        if len(buf) + len(line) > 1500:
            pages.append((pn, buf.strip())); buf = line + "\n"; pn += 1
        else:
            buf += line + "\n"
    if buf.strip():
        pages.append((pn, buf.strip()))
    return _wrap_pages(pages)


def extract_xlsx(fb: bytes):
    if not _HAS_XLSX:
        raise ValueError("openpyxl not installed — cannot read .xlsx")
    wb = openpyxl.load_workbook(io.BytesIO(fb), read_only=True, data_only=True)
    pages = []
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        buf, pn = f"Sheet: {sheet}\n", 1
        for row in ws.iter_rows(values_only=True):
            line = " | ".join(str(c) if c is not None else "" for c in row)
            if len(buf) + len(line) > 1500:
                pages.append((pn, buf.strip())); buf = line + "\n"; pn += 1
            else:
                buf += line + "\n"
        if buf.strip():
            pages.append((pn, buf.strip()))
    wb.close()
    return _wrap_pages(pages)


def extract_pptx(fb: bytes):
    if not _HAS_PPTX:
        raise ValueError("python-pptx not installed — cannot read .pptx")
    prs = Presentation(io.BytesIO(fb))
    pages = []
    for i, slide in enumerate(prs.slides):
        parts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
            if shape.has_table:
                for row in shape.table.rows:
                    parts.append(" | ".join(c.text for c in row.cells))
        pages.append((i + 1, "\n".join(parts)))
    return _wrap_pages(pages)


def extract_html(fb: bytes):
    text = fb.decode("utf-8", errors="replace")
    if _HAS_BS4:
        soup = BeautifulSoup(text, "html.parser")
        clean = soup.get_text(separator="\n", strip=True)
    else:
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = html_mod.unescape(clean)
    return extract_txt(clean.encode("utf-8"))


def extract_markdown(fb: bytes):
    return extract_txt(fb)


def extract_json(fb: bytes):
    text = fb.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        pretty = text
    return extract_txt(pretty.encode("utf-8"))


def extract_xml(fb: bytes):
    try:
        root = ET.fromstring(fb)
        parts = []
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            txt = (elem.text or "").strip()
            if txt:
                parts.append(f"{tag}: {txt}")
        return extract_txt("\n".join(parts).encode("utf-8"))
    except ET.ParseError:
        return extract_txt(fb)


def extract_rtf(fb: bytes):
    if not _HAS_RTF:
        raise ValueError("striprtf not installed — cannot read .rtf")
    text = rtf_to_text(fb.decode("utf-8", errors="replace"))
    return extract_txt(text.encode("utf-8"))


def extract_image(fb: bytes, filename: str):
    """Extract metadata (and any text) from an image file."""
    desc_parts = [f"Image file: {filename}"]
    if _HAS_PIL:
        try:
            img = Image.open(io.BytesIO(fb))
            w, h = img.size
            desc_parts.append(f"Dimensions: {w}x{h}")
            desc_parts.append(f"Mode: {img.mode}")
        except Exception:
            pass
    ocr_text = ""
    try:
        ext = os.path.splitext(filename)[1].lstrip(".")
        doc = fitz.open(stream=fb, filetype=ext)
        if doc.page_count > 0:
            ocr_text = doc[0].get_text().strip()
    except Exception:
        pass

    meta_text = " | ".join(desc_parts)
    if ocr_text:
        meta_text += "\nExtracted text:\n" + ocr_text

    pages = [(1, meta_text)]
    images = [{"data": fb, "ext": os.path.splitext(filename)[1].lstrip("."),
               "page": 1, "desc": desc_parts[0]}]
    return pages, images


# ── Format router ─────────────────────────────────────────

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".svg"}

_EXTRACTOR_MAP = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".txt": extract_txt,
    ".csv": extract_csv,
    ".xlsx": extract_xlsx,
    ".pptx": extract_pptx,
    ".html": extract_html,
    ".htm": extract_html,
    ".md": extract_markdown,
    ".json": extract_json,
    ".xml": extract_xml,
    ".rtf": extract_rtf,
    ".log": extract_txt,
    ".py": extract_txt,
    ".js": extract_txt,
    ".ts": extract_txt,
    ".css": extract_txt,
    ".yaml": extract_txt,
    ".yml": extract_txt,
    ".ini": extract_txt,
    ".cfg": extract_txt,
    ".toml": extract_txt,
}


def _get_extractor(filename: str):
    ext = os.path.splitext(filename.lower())[1]
    if ext in _IMAGE_EXTS:
        return lambda fb: extract_image(fb, filename)
    return _EXTRACTOR_MAP.get(ext)


def get_supported_formats() -> list[str]:
    fmts = sorted(set(list(_EXTRACTOR_MAP.keys()) + list(_IMAGE_EXTS)))
    return fmts


# ── Persistence ───────────────────────────────────────────

def save_persisted_index(embeddings: list):
    """
    Save FAISS index to disk.
    Metadata is already persisted to SQLite incrementally in add_document().
    Embeddings are only needed for FAISS reconstruction, never stored in Python lists.
    """
    try:
        if _faiss_index is not None:
            faiss.write_index(_faiss_index, _INDEX_PATH)
            print(f"[RAG] FAISS index saved ({_faiss_index.ntotal} vectors)")
    except Exception as e:
        print(f"[RAG] WARNING: Failed to persist FAISS index: {e}")


def load_persisted_index():
    """
    Load FAISS index + chunk metadata from disk on server startup.
    Embeddings are NOT reconstructed into Python lists — FAISS holds them natively.
    """
    global _faiss_index
    if os.path.exists(_INDEX_PATH) and os.path.exists(_DB_PATH):
        try:
            print("[RAG] Loading persisted FAISS index and SQLite metadata...")
            _faiss_index = faiss.read_index(_INDEX_PATH)
            _load_metadata_from_db()
            # Sanity check: FAISS vector count should match chunk count
            if _faiss_index.ntotal != len(_chunks):
                print(
                    f"[RAG] WARNING: FAISS has {_faiss_index.ntotal} vectors "
                    f"but DB has {len(_chunks)} chunks — index may be stale."
                )
            print(f"[RAG] Loaded {len(_chunks)} chunks from disk.")
        except Exception as e:
            print(f"[RAG] WARNING: Persisted index corrupted: {e}. Starting fresh.")
            clear_all()
    elif os.path.exists(_DB_PATH) and not os.path.exists(_INDEX_PATH):
        # Metadata exists but FAISS index is missing — load metadata only
        _load_metadata_from_db()
        print("[RAG] SQLite metadata loaded but FAISS index missing. "
              "Re-embedding will rebuild index on next upload.")
    else:
        print("[RAG] No persisted index found — starting fresh.")


# ── Add Document ──────────────────────────────────────────
def add_document(file_bytes: bytes, filename: str) -> int:
    global _chunks, _parent_chunks, _chunk_doc, _chunk_page, _chunk_type, _doc_names, _faiss_index

    if filename in _doc_names:
        return 0

    extractor = _get_extractor(filename)
    if extractor is None:
        supported = ", ".join(get_supported_formats())
        raise ValueError(f"Unsupported file type: {filename!r}. Supported: {supported}")

    result = extractor(file_bytes)
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], list):
        pages, images = result
    else:
        pages, images = result, []

    from llm import get_embed_model
    embed_model = get_embed_model()

    count = 0
    new_chunks = []
    new_parents = []
    new_docs = []
    new_pages = []
    new_types = []
    new_embeddings = []  # Transient — only used for FAISS rebuild, not stored

    # 1. Chunk text by tokens
    for page_num, text in pages:
        if not text.strip():
            continue

        # Parent chunking (512 tokens, 50 token overlap)
        parent_texts = chunk_text_by_tokens(text, embed_model, chunk_size=512, overlap=50)

        for parent_text in parent_texts:
            # Small chunking (256 tokens, 50 token overlap)
            small_texts = chunk_text_by_tokens(parent_text, embed_model, chunk_size=256, overlap=50)

            for small_text in small_texts:
                if not small_text.strip():
                    continue
                new_chunks.append(small_text)
                new_parents.append(parent_text)
                new_docs.append(filename)
                new_pages.append(page_num)
                new_types.append("text")

    # Store image metadata
    if images:
        _images[filename] = images
        for img_info in images:
            meta_chunk = f"[Image in {filename}] {img_info['desc']}"
            new_chunks.append(meta_chunk)
            new_parents.append(meta_chunk)
            new_docs.append(filename)
            new_pages.append(img_info.get("page", 1))
            new_types.append("image_meta")

    # 2. Embed all small chunks (transient — for FAISS index only)
    accepted_chunks = []
    accepted_parents = []
    accepted_docs = []
    accepted_pages = []
    accepted_types = []

    for i in range(len(new_chunks)):
        chunk = new_chunks[i]
        try:
            res = embed_model.create_embedding(chunk)
            vector = res["data"][0]["embedding"]

            accepted_chunks.append(chunk)
            accepted_parents.append(new_parents[i])
            accepted_docs.append(new_docs[i])
            accepted_pages.append(new_pages[i])
            accepted_types.append(new_types[i])
            new_embeddings.append(vector)
            count += 1
        except Exception as e:
            print(f"WARNING: Skipping chunk {i} — embed failed: {chunk[:50]}")

    # 3. Append to in-memory lists
    _chunks.extend(accepted_chunks)
    _parent_chunks.extend(accepted_parents)
    _chunk_doc.extend(accepted_docs)
    _chunk_page.extend(accepted_pages)
    _chunk_type.extend(accepted_types)
    _doc_names.append(filename)

    # 4. Persist metadata to SQLite (incremental — no full rewrite)
    _save_chunks_to_db(
        accepted_chunks, accepted_parents, accepted_docs,
        accepted_pages, accepted_types, filename
    )

    # 5. Build combined embeddings for full FAISS rebuild
    #    We need ALL embeddings (existing + new) to rebuild the index.
    #    For existing vectors we reconstruct from the current FAISS index.
    all_embeddings = []
    if _faiss_index is not None and _faiss_index.ntotal > 0:
        existing_count = _faiss_index.ntotal
        for i in range(existing_count):
            try:
                all_embeddings.append(_faiss_index.reconstruct(i).tolist())
            except Exception:
                pass
    all_embeddings.extend(new_embeddings)

    # 6. Rebuild FAISS with all embeddings
    _rebuild(all_embeddings)

    # 7. Save updated FAISS index to disk
    save_persisted_index(all_embeddings)

    return count


# ── Remove Document ───────────────────────────────────────
def remove_document(filename: str) -> bool:
    global _chunks, _parent_chunks, _chunk_doc, _chunk_page, _chunk_type, _doc_names

    if filename not in _doc_names:
        return False

    keep = [i for i in range(len(_chunks)) if _chunk_doc[i] != filename]

    _chunks = [_chunks[i] for i in keep]
    _parent_chunks = [_parent_chunks[i] for i in keep]
    _chunk_doc = [_chunk_doc[i] for i in keep]
    _chunk_page = [_chunk_page[i] for i in keep]
    _chunk_type = [_chunk_type[i] for i in keep]

    _doc_names.remove(filename)
    _images.pop(filename, None)

    # Delete from SQLite
    _delete_doc_from_db(filename)

    # Rebuild FAISS: reconstruct embeddings from current index for kept chunks
    # We reconstruct ONLY the kept vectors using their original FAISS positions.
    # Since we removed some chunks we need to re-embed or rebuild from scratch.
    # Simplest correct approach: re-embed the kept chunks.
    _rebuild_from_kept_chunks()

    return True


def _rebuild_from_kept_chunks():
    """Re-embed all current in-memory chunks and rebuild the FAISS index."""
    global _faiss_index

    if not _chunks:
        _faiss_index = None
        save_persisted_index([])
        return

    from llm import get_embed_model
    embed_model = get_embed_model()

    embeddings = []
    for chunk in _chunks:
        try:
            res = embed_model.create_embedding(chunk)
            embeddings.append(res["data"][0]["embedding"])
        except Exception:
            embeddings.append([0.0] * 768)  # fallback zero vector

    _rebuild(embeddings)
    save_persisted_index(embeddings)
    print(f"[RAG] FAISS rebuilt from {len(_chunks)} kept chunks")


# ── Clear All ─────────────────────────────────────────────
def clear_all():
    global _chunks, _parent_chunks, _chunk_doc, _chunk_page, _chunk_type, \
           _doc_names, _faiss_index, _images
    _chunks.clear()
    _parent_chunks.clear()
    _chunk_doc.clear()
    _chunk_page.clear()
    _chunk_type.clear()
    _doc_names.clear()
    _images.clear()
    _faiss_index = None

    # Clear SQLite
    _clear_db()

    # Remove FAISS index file
    if os.path.exists(_INDEX_PATH):
        try:
            os.remove(_INDEX_PATH)
        except Exception:
            pass

    # Remove legacy chunks_meta.json if it exists (migration cleanup)
    legacy_meta = os.path.join(USB_ROOT, "chunks_meta.json")
    if os.path.exists(legacy_meta):
        try:
            os.remove(legacy_meta)
            print("[RAG] Removed legacy chunks_meta.json")
        except Exception:
            pass


# ── Search Chunks (Dense Vector) ──────────────────────────
def search_chunks(query: str, top_k: int = 20) -> list[dict]:
    global _faiss_index
    if not _chunks or _faiss_index is None:
        return []

    from llm import get_embed_model
    embed_model = get_embed_model()

    try:
        res = embed_model.create_embedding(query)
        q_vec = np.array(res["data"][0]["embedding"], dtype="float32")
    except Exception as e:
        print(f"[RAG] Failed to embed query: {e}")
        return []

    # Normalize query vector
    norm = np.linalg.norm(q_vec)
    if norm > 0:
        q_vec /= norm

    q_vec = q_vec.reshape(1, -1)
    faiss_scores, faiss_idx = _faiss_index.search(q_vec, min(top_k, len(_chunks)))

    results = []
    for score, idx in zip(faiss_scores[0], faiss_idx[0]):
        if idx >= 0:
            results.append({
                "text": _chunks[idx],
                "parent_text": _parent_chunks[idx],
                "doc": _chunk_doc[idx],
                "page": _chunk_page[idx],
                "faiss_score": float(score),
            })
    return results


# ── Backward Compatible Search ────────────────────────────
def search(query: str, top_k: int = 5) -> str:
    chunks = search_chunks(query, top_k=top_k)
    context = ""
    for c in chunks:
        context += f"[Document: {c['doc']}, page {c['page']}]\n{c['parent_text']}\n\n"
    return context.strip()


# ── Adaptive Search (Dense Embeddings) ─────────────────────
def search_adaptive(query: str, top_k: int = 5) -> dict:
    empty = {"context": "", "confidence": 0.0, "sources": [],
             "has_images": False, "suggestion": ""}

    if not _chunks:
        return empty

    chunks = search_chunks(query, top_k=top_k)
    if not chunks:
        return empty

    top_score = chunks[0]["faiss_score"]
    confidence = max(0.0, min(1.0, (top_score - 0.2) / 0.6))

    MAX_CHARS = 2500
    final = ""
    sources = []

    for c in chunks:
        part = f"[Document: {c['doc']}, page {c['page']}]\n{c['parent_text']}\n\n"
        if len(final) + len(part) > MAX_CHARS:
            break
        final += part
        sources.append({"doc": c["doc"], "page": c["page"], "score": round(c["faiss_score"], 4)})

    has_images = bool(_images)

    suggestion = ""
    if confidence < 0.3 and final:
        doc_names = list(set(s["doc"] for s in sources))
        suggestion = (
            f"The query may not be directly covered, but related "
            f"content was found in: {', '.join(doc_names)}"
        )

    return {
        "context": final.strip(),
        "confidence": round(confidence, 3),
        "sources": sources,
        "has_images": has_images,
        "suggestion": suggestion,
    }


# ── Stats ─────────────────────────────────────────────────
def get_stats() -> dict:
    return {
        "total_chunks": len(_chunks),
        "documents": list(_doc_names),
        "doc_count": len(_doc_names),
        "image_count": sum(len(v) for v in _images.values()),
        "supported_formats": get_supported_formats(),
        "db_path": _DB_PATH,
    }


def get_all_content(max_chars: int = 3500) -> str:
    if not _chunks:
        return ""
    result = ""
    for i, chunk in enumerate(_chunks):
        part = f"[Document: {_chunk_doc[i]}, page {_chunk_page[i]}]\n{_parent_chunks[i]}\n\n"
        if len(result) + len(part) > max_chars:
            break
        result += part
    return result.strip()


def has_documents() -> bool:
    return bool(_chunks)


def get_image_count() -> int:
    return sum(len(v) for v in _images.values())
