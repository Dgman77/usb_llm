"""
crag.py — CRAG (Corrective RAG) Evaluation Layer

Optimized for low-spec CPU environments:
  - Uses pre-computed FAISS scores directly for topic relevance (zero extra embedding dot product checks).
  - High performance, lightweight heuristic checks.
"""

import re

# ── Thresholds ────────────────────────────────────────────────
RERANK_THRESHOLD = 0.30       # Minimum average score to pass
COVERAGE_THRESHOLD = 0.20     # Minimum query term coverage in chunks
DENSITY_THRESHOLD = 100       # Minimum character count in context
COMBINED_THRESHOLD = 0.35     # Minimum combined score to pass
TOPIC_RELEVANCE_THRESHOLD = 0.35


def check_topic_relevance(best_score: float):
    """
    Semantic gate: checks if the highest similarity score
    retrieved from FAISS is above the threshold.
    """
    return best_score >= TOPIC_RELEVANCE_THRESHOLD, best_score


def evaluate(query: str, chunks: list[dict]) -> dict:
    """
    Evaluate if retrieved chunks are relevant and sufficient to answer the query.
    Uses pre-calculated FAISS scores and term coverage.
    
    Args:
        query:  The user's original question
        chunks: List of retrieved chunks with 'text', 'parent_text', 'faiss_score'
        
    Returns:
        {
            "pass": bool,           # True if chunks are sufficient
            "score": float,         # Combined confidence 0.0–1.0
            "reason": str,          # Human-readable evaluation reason
            "context": str,         # Assembled context string (if pass)
        }
    """
    if not chunks:
        return {
            "pass": False,
            "score": 0.0,
            "reason": "No chunks retrieved",
            "context": "",
        }

    # Step 1: Semantic relevance topic check using pre-computed FAISS score
    best_score = chunks[0].get("faiss_score", 0.0)
    is_rel, best_similarity = check_topic_relevance(best_score)
    if not is_rel:
        return {
            "pass": False,
            "reason": "out_of_domain",
            "best_similarity": best_similarity,
            "score": 0.0,
            "context": ""
        }

    # ── Signal 1: Similarity score analysis ───────────────────
    scores = [c.get("faiss_score", 0.0) for c in chunks]
    avg_score = sum(scores) / len(scores)
    top_score = scores[0]
    similarity_signal = min(1.0, (avg_score + top_score) / 2)

    # ── Signal 2: Query term coverage ─────────────────────────
    query_terms = set(_tokenize(query))
    if query_terms:
        all_chunk_text = " ".join(
            (c.get("parent_text") or c.get("text", "")) for c in chunks
        ).lower()
        covered = sum(1 for t in query_terms if t in all_chunk_text)
        coverage_signal = covered / len(query_terms)
    else:
        coverage_signal = 0.0

    # ── Signal 3: Content density check ───────────────────────
    context = _build_context(chunks)
    content_length = len(context)
    density_signal = min(1.0, content_length / 500)  # Saturates at 500 chars

    # ── Combined score ────────────────────────────────────────
    # Weighted: similarity quality (40%) + coverage (35%) + density (25%)
    combined = (similarity_signal * 0.40) + (coverage_signal * 0.35) + (density_signal * 0.25)

    passed = combined >= COMBINED_THRESHOLD and content_length >= DENSITY_THRESHOLD

    # Build reason string
    if passed:
        reason = (f"Context verified (score={combined:.2f}): "
                  f"similarity={similarity_signal:.2f}, coverage={coverage_signal:.2f}, "
                  f"density={density_signal:.2f}")
    else:
        reasons = []
        if similarity_signal < RERANK_THRESHOLD:
            reasons.append(f"low similarity quality ({similarity_signal:.2f})")
        if coverage_signal < COVERAGE_THRESHOLD:
            reasons.append(f"poor query coverage ({coverage_signal:.2f})")
        if content_length < DENSITY_THRESHOLD:
            reasons.append(f"insufficient content ({content_length} chars)")
        if not reasons:
            reasons.append(f"combined score too low ({combined:.2f})")
        reason = f"Context rejected (score={combined:.2f}): " + "; ".join(reasons)

    print(f"[CRAG] {'PASS' if passed else 'FAIL'} | {reason}")

    return {
        "pass": passed,
        "score": round(combined, 3),
        "reason": reason,
        "context": context if passed else "",
    }


def _build_context(chunks: list[dict], max_chars: int = 3500) -> str:
    """Assemble context string from chunks, preferring parent chunks."""
    context = ""
    seen = set()

    for chunk in chunks:
        text = chunk.get("parent_text") or chunk.get("text", "")
        # Deduplicate by first 80 chars
        key = text[:80]
        if key in seen:
            continue
        seen.add(key)

        part = f"[Source: {chunk.get('doc', '?')}, page {chunk.get('page', '?')}]\n{text}\n\n"
        if len(context) + len(part) > max_chars:
            break
        context += part

    return context.strip()


def _tokenize(text: str) -> list[str]:
    """Simple tokenization for coverage check."""
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "each", "every", "both", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "because", "and", "but",
        "or", "if", "while", "about", "up", "its", "it", "this", "that",
        "what", "which", "who", "whom", "me", "my", "i", "you", "your",
        "he", "she", "we", "they", "his", "her", "our", "their",
    }
    words = re.findall(r"\b[a-z]{2,}\b", text.lower())
    return [w for w in words if w not in stop]
