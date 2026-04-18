"""
rag.py — Hybrid RAG (BM25 + FAISS) with smart chunking + fast retrieval
Supports: PDF, DOCX, TXT
Session-only storage — all data lives in RAM, cleared on server restart/tab close
"""

import os
import re
import numpy as np

# ── Imports ─────────────────────────────────────────
from rank_bm25 import BM25Okapi
import faiss
import fitz  # PDF  → PyMuPDF
from docx import Document as DocxDoc  # DOCX → python-docx
import io

# ── State (in-memory only) ─────────────────────────
_chunks = []
_tokenized = []
_chunk_doc = []
_chunk_page = []
_doc_names = []
_vocab = {}

_bm25 = None
_faiss_index = None


# ── Tokenize ────────────────────────────────────────
def _tokenize(text: str):
    return re.findall(r"\b[a-z]{2,}\b", text.lower())


# ── Sentence chunking ────────────────────────────────
def chunk_text(text: str, max_chars: int = 600):
    """
    Chunk text into meaningful segments.
    For diagrams, larger chunks (600 chars) help capture complete entities.
    """
    # Split by double newlines first (paragraphs), then by sentences
    paragraphs = re.split(r"\n\s*\n", text)
    chunks = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If paragraph is small, add it directly
        if len(para) <= max_chars:
            chunks.append(para)
        else:
            # Split long paragraphs by sentences
            sentences = re.split(r"(?<=[.?!])\s+", para)
            current = ""
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                if len(current) + len(sent) + 1 <= max_chars:
                    current += (" " + sent) if current else sent
                else:
                    if current:
                        chunks.append(current.strip())
                    current = sent
            if current:
                chunks.append(current.strip())

    # Ensure we have chunks
    return chunks if chunks else [text[:max_chars]]


# ── Build Hybrid Index ──────────────────────────────
def _rebuild():
    global _bm25, _faiss_index, _tokenized, _vocab

    if not _chunks:
        return

    _tokenized = [_tokenize(c) for c in _chunks]
    _bm25 = BM25Okapi(_tokenized)

    vocab: dict = {}
    for tokens in _tokenized:
        for t in tokens:
            if t not in vocab:
                vocab[t] = len(vocab)

    dim = max(len(vocab), 1)
    mat = np.zeros((len(_chunks), dim), dtype="float32")

    for i, tokens in enumerate(_tokenized):
        for t in tokens:
            if t in vocab:
                mat[i][vocab[t]] += 1
        norm = np.linalg.norm(mat[i])
        if norm > 0:
            mat[i] /= norm

    _faiss_index = faiss.IndexFlatIP(dim)
    _faiss_index.add(mat)
    _vocab = vocab


# ── Extractors (all return (page_num, text) tuples) ─
def extract_pdf(file_bytes: bytes) -> list[tuple[int, str]]:
    """Return [(page_num, text), ...] from a PDF."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    return [(i + 1, page.get_text()) for i, page in enumerate(doc)]


def extract_docx(file_bytes: bytes) -> list[tuple[int, str]]:
    """Return [(page_num, text), ...] from a DOCX."""
    doc = DocxDoc(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    pages, buf, page_num = [], "", 1
    for para in paragraphs:
        if len(buf) + len(para) > 1500:
            pages.append((page_num, buf.strip()))
            buf = para + "\n"
            page_num += 1
        else:
            buf += para + "\n"
    if buf.strip():
        pages.append((page_num, buf.strip()))
    return pages


def extract_txt(file_bytes: bytes) -> list[tuple[int, str]]:
    """Return [(page_num, text), ...] from a plain-text file."""
    text = file_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()
    pages, buf, page_num = [], "", 1
    for line in lines:
        if len(buf) + len(line) > 1500:
            pages.append((page_num, buf.strip()))
            buf = line + "\n"
            page_num += 1
        else:
            buf += line + "\n"
    if buf.strip():
        pages.append((page_num, buf.strip()))
    return pages


def _get_extractor(filename: str):
    ext = os.path.splitext(filename.lower())[1]
    return {
        ".pdf": extract_pdf,
        ".docx": extract_docx,
        ".txt": extract_txt,
    }.get(ext)


# ── Add Document ────────────────────────────────────
def add_document(file_bytes: bytes, filename: str) -> int:
    """Ingest a PDF, DOCX, or TXT file into the hybrid index. Returns chunk count."""
    global _chunks, _chunk_doc, _chunk_page, _doc_names

    if filename in _doc_names:
        return 0

    extractor = _get_extractor(filename)
    if extractor is None:
        raise ValueError(
            f"Unsupported file type: {filename!r}  (use .pdf / .docx / .txt)"
        )

    pages = extractor(file_bytes)
    count = 0

    for page_num, text in pages:
        for chunk in chunk_text(text):
            _chunks.append(chunk)
            _chunk_doc.append(filename)
            _chunk_page.append(page_num)
            count += 1

    _doc_names.append(filename)
    _rebuild()

    return count


# ── Remove Document ─────────────────────────────────
def remove_document(filename: str) -> bool:
    """Remove all chunks belonging to a document. Returns True if doc was found."""
    global _chunks, _chunk_doc, _chunk_page, _doc_names

    if filename not in _doc_names:
        return False

    keep_indices = [i for i in range(len(_chunks)) if _chunk_doc[i] != filename]

    _chunks = [_chunks[i] for i in keep_indices]
    _chunk_doc = [_chunk_doc[i] for i in keep_indices]
    _chunk_page = [_chunk_page[i] for i in keep_indices]
    _doc_names.remove(filename)

    _rebuild()
    return True


# ── Clear All ────────────────────────────────────────
def clear_all():
    """Nuke the entire in-memory index."""
    global _chunks, _tokenized, _chunk_doc, _chunk_page, _doc_names, _bm25, _faiss_index

    _chunks.clear()
    _tokenized.clear()
    _chunk_doc.clear()
    _chunk_page.clear()
    _doc_names.clear()
    _bm25 = None
    _faiss_index = None


# ── Query Vector (FAISS) ────────────────────────────
def _vectorize_query(tokens: list[str]) -> np.ndarray:
    vec = np.zeros(len(_vocab), dtype="float32")
    for t in tokens:
        if t in _vocab:
            vec[_vocab[t]] += 1
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


# ── Hybrid Search ───────────────────────────────────
def search(query: str, top_k: int = 5) -> str:
    if not _chunks:
        return ""

    tokens = _tokenize(query)
    if not tokens:
        return ""

    bm25_scores = np.array(_bm25.get_scores(tokens))

    q_vec = _vectorize_query(tokens)
    faiss_scores, faiss_idx = _faiss_index.search(
        q_vec.reshape(1, -1), min(20, len(_chunks))
    )

    combined: dict[int, float] = {}
    # Weight FAISS (semantic) higher for conceptual queries, BM25 (lexical) for specific terms
    for score, idx in zip(faiss_scores[0], faiss_idx[0]):
        combined[idx] = combined.get(idx, 0) + float(score) * 0.5
    for i, s in enumerate(bm25_scores):
        combined[i] = combined.get(i, 0) + float(s) * 0.5

    ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)

    selected, seen_text = [], set()
    for idx, _ in ranked:
        # Deduplicate by first 100 chars (more aggressive)
        key = _chunks[idx][:100]
        if key in seen_text:
            continue
        selected.append(idx)
        seen_text.add(key)
        if len(selected) >= top_k:
            break

    if not selected:
        return ""

    MAX_CHARS = 2000  # Increased from 1500 for more diagram detail
    final = ""
    best_score = ranked[0][1] if ranked else 0

    for i in selected:
        part = f"[Document: {_chunk_doc[i]}, page {_chunk_page[i]}]\n{_chunks[i]}\n\n"
        if len(final) + len(part) > MAX_CHARS:
            break
        final += part

    # Lower confidence threshold since score distribution changed
    if best_score < 0.02:
        final = "[Note: Low relevance to query]\n\n" + final

    return final.strip()


# ── Stats ───────────────────────────────────────────
def get_stats() -> dict:
    return {
        "total_chunks": len(_chunks),
        "documents": list(_doc_names),
        "doc_count": len(_doc_names),
        "session_only": True,
    }


def has_documents() -> bool:
    return bool(_chunks)
