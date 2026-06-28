"""
reranker.py — BGE Reranker pass-through.
Disabled for low-spec CPU optimization to eliminate memory swaps.
"""

def rerank(query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """
    Pass-through: Returns chunks sorted by FAISS score.
    """
    for c in chunks:
        c["rerank_score"] = c.get("faiss_score", 0.0)
    chunks.sort(key=lambda c: c["rerank_score"], reverse=True)
    return chunks[:top_k]
