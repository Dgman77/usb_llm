"""
reranker.py — BGE Reranker via Dedicated Reranker GGUF Model

After FAISS retrieves top-k candidate chunks, this module re-scores each
(query, chunk) pair using the BGE reranker GGUF model as a cross-encoder.
If the reranker model is not available, falls back to FAISS similarity scores.

Key difference from v1: Uses dedicated reranker model (~636MB) instead of
the full chat model (~2-4GB), avoiding catastrophic memory swaps on 8GB systems.
"""

import numpy as np

RERANKER_CHUNK_MAX_CHARS = 1500
# Increase for better rerank accuracy.
# Decrease if reranker is too slow on large docs.


def rerank(query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """
    Re-rank retrieved chunks using the dedicated BGE reranker model.
    
    Strategy:
      1. Try to load the BGE reranker GGUF model
      2. Embed (query, chunk) pairs and compute cross-similarity
      3. If reranker unavailable, fall back to FAISS scores
    
    Args:
        query:  The user's original query
        chunks: List of dicts with keys: text, doc, page, faiss_score, parent_text
        top_k:  Number of top chunks to return after reranking
        
    Returns:
        Sorted list of top-k chunks with added 'rerank_score' field
    """
    if not chunks:
        return []

    if len(chunks) <= 1:
        for c in chunks:
            c["rerank_score"] = c.get("faiss_score", 0.5)
        return chunks

    # Try dedicated reranker model
    try:
        from llm import get_reranker_model, unload_reranker
        reranker = get_reranker_model()
        
        if reranker is not None:
            result = _rerank_with_model(reranker, query, chunks, top_k)
            unload_reranker()  # Free memory after reranking
            return result
    except Exception as e:
        print(f"[Reranker] Reranker model failed: {e} — falling back to FAISS scores")
    
    # Fallback: use FAISS similarity scores directly
    return _fallback_rerank(chunks, top_k)


def _rerank_with_model(reranker, query: str, chunks: list[dict], top_k: int) -> list[dict]:
    """Re-rank using the BGE reranker model via embedding similarity."""
    try:
        # Embed the query
        q_res = reranker.create_embedding(query)
        q_vec = np.array(q_res["data"][0]["embedding"], dtype="float32")
        q_norm = np.linalg.norm(q_vec)
        if q_norm > 0:
            q_vec /= q_norm
    except Exception as e:
        print(f"[Reranker] Failed to embed query: {e}")
        return _fallback_rerank(chunks, top_k)
    
    # LIMITATION: llama.cpp does not expose cross-encoder
    # logits natively. This is the closest approximation
    # possible with current llama-cpp-python API.
    for chunk in chunks:
        text = chunk.get("parent_text") or chunk.get("text", "")
        # Truncate very long chunks for the reranker
        text = text[:RERANKER_CHUNK_MAX_CHARS]
        try:
            c_res = reranker.create_embedding(text)
            c_vec = np.array(c_res["data"][0]["embedding"], dtype="float32")
            c_norm = np.linalg.norm(c_vec)
            if c_norm > 0:
                c_vec /= c_norm
            # Cosine similarity
            score = float(np.dot(q_vec, c_vec))
            chunk["rerank_score"] = max(0.0, min(1.0, score))
        except Exception:
            chunk["rerank_score"] = chunk.get("faiss_score", 0.0)

    # Sort by rerank score (descending) — precision-first
    chunks.sort(key=lambda c: c["rerank_score"], reverse=True)
    result = chunks[:top_k]

    # Log for debugging
    if result:
        top = result[0]["rerank_score"]
        bot = result[-1]["rerank_score"] if len(result) > 1 else top
        print(f"[Reranker] BGE model: {len(chunks)} → {len(result)} chunks | "
              f"scores: {top:.2f} .. {bot:.2f}")

    return result


def _fallback_rerank(chunks: list[dict], top_k: int) -> list[dict]:
    """Fallback reranking using FAISS scores directly."""
    for c in chunks:
        c["rerank_score"] = c.get("faiss_score", 0.0)
    
    chunks.sort(key=lambda c: c["rerank_score"], reverse=True)
    result = chunks[:top_k]
    
    if result:
        top = result[0]["rerank_score"]
        bot = result[-1]["rerank_score"] if len(result) > 1 else top
        print(f"[Reranker] Fallback (FAISS scores): {len(chunks)} → {len(result)} chunks | "
              f"scores: {top:.2f} .. {bot:.2f}")
    
    return result
