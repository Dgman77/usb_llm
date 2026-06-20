"""
rag.py — Dense RAG with multi-format + image support
Supports: PDF, DOCX, TXT, CSV, XLSX, PPTX, HTML, MD, JSON, XML, RTF, Images

# Search: Dense vector search via FAISS IndexFlatIP
# with cosine similarity (L2 normalisation).
# BM25 sparse search not implemented — dense only.
"""

import os
import re
import io
import csv
import json
import base64
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
_embeddings = []        # list of list of floats
_images = {}            # doc_name → [{data, ext, page, desc}, ...]
_faiss_index = None


# ── Chunking by Tokens ────────────────────────────────────
def chunk_text_by_tokens(text: str, model, chunk_size: int, overlap: int) -> list[str]:
    """Split text into chunks of specified tokens with overlap using model tokenizer."""
    try:
        tokens = model.tokenize(text.encode('utf-8', errors='ignore'))
    except Exception as e:
        print(f"[RAG] Tokenizer failed: {e} — falling back to word-based approximation")
        # Fallback to word-based chunking if model tokenizer fails
        words = text.split()
        chunks = []
        i = 0
        while i < len(words):
            chunk_words = words[i : i + chunk_size]
            chunks.append(" ".join(chunk_words))
            if i + chunk_size >= len(words):
                break
            i += (chunk_size - overlap)
        return chunks

    chunks = []
    i = 0
    while i < len(tokens):
        chunk_tokens = tokens[i : i + chunk_size]
        try:
            chunk_text = model.detokenize(chunk_tokens).decode('utf-8', errors='ignore')
        except Exception:
            chunk_text = ""
        if chunk_text.strip():
            chunks.append(chunk_text)
        if i + chunk_size >= len(tokens):
            break
        i += (chunk_size - overlap)
    return chunks if chunks else [text]


# ── Build FAISS Index ─────────────────────────────────────
def _rebuild():
    global _faiss_index
    if not _embeddings:
        _faiss_index = None
        return

    dim = len(_embeddings[0])
    mat = np.array(_embeddings, dtype="float32")

    # Normalize each vector for Cosine Similarity (via Inner Product Flat index)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    mat = mat / norms

    _faiss_index = faiss.IndexFlatIP(mat.shape[1])
    _faiss_index.add(mat)
    print(f"[RAG] FAISS Index rebuilt with {len(_embeddings)} chunks (dim={dim})")


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
    header = rows[0] if rows else []
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
    # Try PIL for dimensions
    if _HAS_PIL:
        try:
            img = Image.open(io.BytesIO(fb))
            w, h = img.size
            desc_parts.append(f"Dimensions: {w}x{h}")
            desc_parts.append(f"Mode: {img.mode}")
        except Exception:
            pass
    # Try PyMuPDF to extract any embedded text (OCR layer)
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


# USB-safe root path for persistence
USB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def save_persisted_index():
    try:
        index_path = os.path.join(USB_ROOT, "index.faiss")
        meta_path = os.path.join(USB_ROOT, "chunks_meta.json")
        if _faiss_index is not None:
            faiss.write_index(_faiss_index, index_path)
            metadata = {
                "chunks": _chunks,
                "parent_chunks": _parent_chunks,
                "chunk_doc": _chunk_doc,
                "chunk_page": _chunk_page,
                "chunk_type": _chunk_type,
                "doc_names": _doc_names
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            print("[RAG] FAISS index and metadata saved to disk.")
    except Exception as e:
        print(f"[RAG] WARNING: Failed to persist index: {e}")


def load_persisted_index():
    global _chunks, _parent_chunks, _chunk_doc, _chunk_page, _chunk_type, _doc_names, _embeddings, _faiss_index
    index_path = os.path.join(USB_ROOT, "index.faiss")
    meta_path = os.path.join(USB_ROOT, "chunks_meta.json")
    if os.path.exists(index_path) and os.path.exists(meta_path):
        try:
            print("[RAG] Loading persisted FAISS index and metadata...")
            _faiss_index = faiss.read_index(index_path)
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            _chunks = metadata["chunks"]
            _parent_chunks = metadata["parent_chunks"]
            _chunk_doc = metadata["chunk_doc"]
            _chunk_page = metadata["chunk_page"]
            _chunk_type = metadata["chunk_type"]
            _doc_names = metadata["doc_names"]
            # Reconstruct embeddings from FAISS
            _embeddings = [_faiss_index.reconstruct(i).tolist() for i in range(_faiss_index.ntotal)]
            print(f"[RAG] Loaded {len(_chunks)} chunks from disk.")
        except Exception as e:
            print(f"[RAG] WARNING: Persisted index files corrupted or invalid: {e}. Starting fresh.")
            clear_all()


# ── Add Document ──────────────────────────────────────────
def add_document(file_bytes: bytes, filename: str) -> int:
    global _chunks, _parent_chunks, _chunk_doc, _chunk_page, _chunk_type, _doc_names, _embeddings, _faiss_index

    if filename in _doc_names:
        return 0

    extractor = _get_extractor(filename)
    if extractor is None:
        supported = ", ".join(get_supported_formats())
        raise ValueError(f"Unsupported file type: {filename!r}. Supported: {supported}")

    result = extractor(file_bytes)
    # Extractors return either (pages, images) or just pages
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], list):
        pages, images = result
    else:
        pages, images = result, []

    from llm import get_embed_model, unload_model
    embed_model = get_embed_model()

    count = 0
    new_chunks = []
    new_parents = []
    new_docs = []
    new_pages = []
    new_types = []

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

    # 2. Embed all small chunks, skipping failed ones (FIX-5)
    for i in range(len(new_chunks)):
        chunk = new_chunks[i]
        try:
            res = embed_model.create_embedding(chunk)
            vector = res["data"][0]["embedding"]
            
            # Append only if embedding succeeds
            _chunks.append(chunk)
            _parent_chunks.append(new_parents[i])
            _chunk_doc.append(new_docs[i])
            _chunk_page.append(new_pages[i])
            _chunk_type.append(new_types[i])
            _embeddings.append(vector)
            count += 1
        except Exception as e:
            print(f"WARNING: Skipping chunk {i} — embed failed: {chunk[:50]}")

    _doc_names.append(filename)

    # Rebuild FAISS index
    _rebuild()
    
    # Save index & metadata to disk (FIX-4)
    save_persisted_index()

    # Unload embed model to free memory
    unload_model()

    return count


# ── Remove Document ───────────────────────────────────────
def remove_document(filename: str) -> bool:
    global _chunks, _parent_chunks, _chunk_doc, _chunk_page, _chunk_type, _doc_names, _embeddings

    if filename not in _doc_names:
        return False

    keep = [i for i in range(len(_chunks)) if _chunk_doc[i] != filename]
    
    _chunks = [_chunks[i] for i in keep]
    _parent_chunks = [_parent_chunks[i] for i in keep]
    _chunk_doc = [_chunk_doc[i] for i in keep]
    _chunk_page = [_chunk_page[i] for i in keep]
    _chunk_type = [_chunk_type[i] for i in keep]
    _embeddings = [_embeddings[i] for i in keep]
    
    _doc_names.remove(filename)
    _images.pop(filename, None)

    _rebuild()
    
    # Save index after removal (FIX-4)
    save_persisted_index()
    return True


# ── Clear All ─────────────────────────────────────────────
def clear_all():
    global _chunks, _parent_chunks, _chunk_doc, _chunk_page, _chunk_type, _doc_names, _embeddings, _faiss_index, _images
    _chunks.clear()
    _parent_chunks.clear()
    _chunk_doc.clear()
    _chunk_page.clear()
    _chunk_type.clear()
    _embeddings.clear()
    _doc_names.clear()
    _images.clear()
    _faiss_index = None
    
    # Remove persisted files
    index_path = os.path.join(USB_ROOT, "index.faiss")
    meta_path = os.path.join(USB_ROOT, "chunks_meta.json")
    if os.path.exists(index_path):
        try:
            os.remove(index_path)
        except Exception:
            pass
    if os.path.exists(meta_path):
        try:
            os.remove(meta_path)
        except Exception:
            pass
    
    from llm import unload_model
    unload_model()


# ── Search Chunks (Dense Vector) ──────────────────────────
def search_chunks(query: str, top_k: int = 20) -> list[dict]:
    global _faiss_index
    if not _chunks or _faiss_index is None:
        return []

    from llm import get_embed_model, unload_model
    embed_model = get_embed_model()

    try:
        res = embed_model.create_embedding(query)
        q_vec = np.array(res["data"][0]["embedding"], dtype="float32")
    except Exception as e:
        print(f"[RAG] Failed to embed query: {e}")
        unload_model()
        return []

    # Normalize query vector
    norm = np.linalg.norm(q_vec)
    if norm > 0:
        q_vec /= norm

    # Unload embed model to free memory
    unload_model()

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

    # ── Confidence scoring based on top FAISS similarity score ──
    # Cosine similarity for normalized vectors is in range [-1, 1], usually [0.3, 0.8] for text
    top_score = chunks[0]["faiss_score"]
    confidence = max(0.0, min(1.0, (top_score - 0.2) / 0.6))

    # ── Build context ─────────────────────────────────────
    MAX_CHARS = 2500
    final = ""
    sources = []
    has_images = False

    for c in chunks:
        part = f"[Document: {c['doc']}, page {c['page']}]\n{c['parent_text']}\n\n"
        if len(final) + len(part) > MAX_CHARS:
            break
        final += part
        sources.append({"doc": c["doc"], "page": c["page"], "score": round(c["faiss_score"], 4)})
        
    # Check if any document has images
    if _images:
        has_images = True

    # Suggestion for low confidence
    suggestion = ""
    if confidence < 0.3 and final:
        doc_names = list(set(s["doc"] for s in sources))
        suggestion = (f"The query may not be directly covered, but related "
                      f"content was found in: {', '.join(doc_names)}")

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
        "session_only": True,
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
