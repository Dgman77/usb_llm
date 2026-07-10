"""
orchestrator.py — Central brain of the system.

Routes every user request to one of 5 paths:

  1. GENERAL QA     — No documents OR query is off-topic from documents.
  2. RAG QA         — Documents present AND query is relevant to them.
  3. GENERAL DIAGRAM — Diagram request, no document context needed.
  4. RAG DIAGRAM    — Diagram explicitly from an uploaded document.
  5. RAG → DIAGRAM  — Diagram whose topic was retrieved via RAG search.

The orchestrator runs:
  HyDE query rewriting → FAISS retrieval → CRAG evaluation → route decision
"""

import re
import os
from router import route, detect_diagram_type, user_wants_doc_to_diagram
from rag import search_chunks, has_documents, get_all_content
from llm import generate, load_model
from crag import evaluate, TOPIC_RELEVANCE_THRESHOLD

DIAGRAM_RELEVANCE_THRESHOLD = 0.42

# HyDE adds a full second LLM inference call (150 tokens) before every RAG
# query, adding 15-45 seconds latency on CPU. Disabled by default.
# Set environment variable HYDE_ENABLED=1 to re-enable.
_HYDE_ENABLED = os.environ.get("HYDE_ENABLED", "0").strip() == "1"
if _HYDE_ENABLED:
    from hyde import rewrite_query
else:
    def rewrite_query(query: str) -> str:
        """Fast passthrough: returns the raw query for embedding."""
        return query


# ── Main Entry Point ───────────────────────────────────────────────────────────

def handle_request(user_message: str) -> dict:
    """
    Dispatch user request to the correct one of 5 routes.
    Returns a JSON-serialisable dict with at least {mode, response}.
    """
    mode = route(user_message)
    diagram_type = detect_diagram_type(user_message)

    # ══════════════════════════════════════════════════════════════════════
    #  DIAGRAM ROUTES
    # ══════════════════════════════════════════════════════════════════════
    if mode == "diagram":
        return _handle_diagram(user_message, diagram_type)

    # ══════════════════════════════════════════════════════════════════════
    #  QA ROUTES
    # ══════════════════════════════════════════════════════════════════════
    return _handle_qa(user_message)


# ── Diagram Dispatcher ─────────────────────────────────────────────────────────

def _handle_diagram(user_message: str, diagram_type: str) -> dict:
    """
    Routes to one of three diagram paths:
      • ROUTE 3 — General Diagram (no documents / not about document)
      • ROUTE 4 — RAG Diagram (explicitly from uploaded document)
      • ROUTE 5 — RAG→Diagram (topic retrieved from docs, then diagrammed)
    """
    explicitly_from_doc = user_wants_doc_to_diagram(user_message)

    # ── ROUTE 4: RAG Diagram (user explicitly says "from my document") ──
    if explicitly_from_doc:
        if not has_documents():
            print(f"[Orchestrator] ROUTE 4 — No documents uploaded. Falling back to ROUTE 3 (General Diagram)")
            response = generate(
                prompt=user_message,
                mode="diagram",
                diagram_type=diagram_type,
                context="",
            )
            comment = "// Note: No documents uploaded yet. Generated from general knowledge.\n"
            if response.strip().startswith("digraph") or response.strip().startswith("graph"):
                response = comment + response
            return {
                "mode": "diagram",
                "response": response,
                "layout_engine": diagram_type,
                "route": "general_diagram_fallback",
            }
        context = get_all_content(max_chars=3500)
        context = _strip_source_headers(context)
        print(f"[Orchestrator] ROUTE 4 — RAG Diagram from document ({len(context)} chars)")
        return {
            "mode": "diagram",
            "response": generate(
                prompt=user_message,
                mode="diagram",
                diagram_type=diagram_type,
                context=context,
            ),
            "layout_engine": diagram_type,
            "route": "rag_diagram",
        }

    # ── ROUTE 5: RAG→Diagram (documents exist, try to find relevant content) ──
    if has_documents():
        search_query = _strip_diagram_keywords(user_message) or user_message
        chunks = search_chunks(search_query, top_k=6)

        if chunks:
            best_score = chunks[0].get("faiss_score", 0.0)
            if best_score >= DIAGRAM_RELEVANCE_THRESHOLD:
                context = _build_context_from_chunks(chunks, max_chars=3000)
                context = _strip_source_headers(context)
                print(f"[Orchestrator] ROUTE 5 — RAG→Diagram (score={best_score:.3f})")
                return {
                    "mode": "diagram",
                    "response": generate(
                        prompt=user_message,
                        mode="diagram",
                        diagram_type=diagram_type,
                        context=context,
                    ),
                    "layout_engine": diagram_type,
                    "route": "rag_to_diagram",
                }

    # ── ROUTE 3: General Diagram ──────────────────────────────────────────────
    print(f"[Orchestrator] ROUTE 3 — General Diagram")
    return {
        "mode": "diagram",
        "response": generate(
            prompt=user_message,
            mode="diagram",
            diagram_type=diagram_type,
            context="",
        ),
        "layout_engine": diagram_type,
        "route": "general_diagram",
    }


# ── QA Dispatcher ──────────────────────────────────────────────────────────────

def _handle_qa(user_message: str) -> dict:
    """
    Routes to one of two QA paths:
      • ROUTE 1 — General QA (no docs, or query is off-topic)
      • ROUTE 2 — RAG QA (documents relevant to query)
    """
    # ── ROUTE 1a: No documents uploaded at all ────────────────────────────────
    if not has_documents():
        print(f"[Orchestrator] ROUTE 1 — General QA (no documents)")
        return {
            "mode": "qa",
            "response": generate(prompt=user_message, mode="qa"),
            "route": "general_qa",
        }

    # ── Fast precheck: is this query even related to our documents? ───────────
    precheck_chunks = search_chunks(user_message, top_k=3)
    if not precheck_chunks:
        # No FAISS results at all → general
        print(f"[Orchestrator] ROUTE 1 — General QA (empty FAISS results)")
        return {
            "mode": "qa",
            "response": generate(prompt=user_message, mode="qa"),
            "route": "general_qa",
        }

    best_score = precheck_chunks[0].get("faiss_score", 0.0)
    if best_score < TOPIC_RELEVANCE_THRESHOLD:
        # Query is off-topic from documents → General QA
        print(
            f"[Orchestrator] ROUTE 1 — General QA "
            f"(precheck score {best_score:.3f} < {TOPIC_RELEVANCE_THRESHOLD})"
        )
        return {
            "mode": "qa",
            "response": generate(prompt=user_message, mode="qa"),
            "route": "general_qa",
        }

    print(
        f"[Orchestrator] Precheck PASSED (score={best_score:.3f}) — "
        f"proceeding with full RAG pipeline..."
    )

    # ── ROUTE 2: Full RAG QA ──────────────────────────────────────────────────

    # Step 1: Query rewriting (HyDE if enabled, else raw query)
    if _HYDE_ENABLED:
        print(f"[Orchestrator] Step 1 — HyDE query rewriting...")
        hyde_query = rewrite_query(user_message)
        print(f"[Orchestrator] HyDE: {hyde_query[:100]}...")
    else:
        hyde_query = user_message
        print(f"[Orchestrator] Step 1 — Using raw query (HyDE disabled for speed)")

    # Step 2: Dense FAISS retrieval with HyDE query
    print(f"[Orchestrator] Step 2 — FAISS retrieval (top 10)...")
    chunks = search_chunks(hyde_query, top_k=10)

    if not chunks:
        # HyDE search returned nothing (edge case)
        print(f"[Orchestrator] HyDE search empty — falling back to general QA")
        return {
            "mode": "qa",
            "response": generate(prompt=user_message, mode="qa"),
            "route": "general_qa",
        }

    # Step 3: CRAG evaluation — validates chunk quality before passing to LLM
    print(f"[Orchestrator] Step 3 — CRAG evaluation...")
    eval_res = evaluate(user_message, chunks)

    # Build source list for the response
    sources = [
        {
            "doc": c["doc"],
            "page": c["page"],
            "score": round(c.get("faiss_score", 0.0), 4),
        }
        for c in chunks[:5]
    ]

    # ── CRAG hard block: out-of-domain ───────────────────────────────────────
    if eval_res.get("reason") == "out_of_domain":
        print(f"[Orchestrator] CRAG blocked — out_of_domain. Falling back to General QA...")
        gen_response = generate(prompt=user_message, mode="qa")
        fallback_msg = (
            "Note: This information is not available in the uploaded document. "
            "Answering from general knowledge:\n\n" + gen_response
        )
        return {
            "mode": "qa",
            "response": fallback_msg,
            "sources": [],
            "crag_status": "out_of_domain_fallback",
            "crag_score": eval_res["score"],
            "crag_reason": eval_res["reason"],
            "route": "general_qa_fallback",
        }

    # ── CRAG passed ───────────────────────────────────────────────────────────
    if eval_res["pass"]:
        print(
            f"[Orchestrator] ROUTE 2 — RAG QA "
            f"(CRAG passed, score={eval_res['score']:.3f})"
        )
        response = generate(
            prompt=user_message,
            mode="doc_qa",
            context=eval_res["context"],
            confidence=eval_res["score"],
        )

        # Detect if the LLM itself refused (no info in doc)
        refusal_phrases = [
            "does not contain sufficient information",
            "do not contain specific information",
            "insufficient information",
            "not mentioned in the context",
            "this information is not available in the uploaded document",
        ]
        is_refusal = any(p in response.lower() for p in refusal_phrases)

        if not is_refusal:
            doc_names = []
            for c in chunks:
                d = c.get("doc")
                if d and d not in doc_names:
                    doc_names.append(d)
            doc_names_str = ", ".join(doc_names) if doc_names else "Document"
            response = f"Your Data from {doc_names_str}:\n{response}"
        else:
            print(f"[Orchestrator] LLM refused. Falling back to General QA...")
            gen_response = generate(prompt=user_message, mode="qa")
            response = (
                "Note: The uploaded documents do not contain specific information on this. "
                "Answering from general knowledge:\n\n" + gen_response
            )

        return {
            "mode": "qa",
            "response": response,
            "sources": sources,
            "crag_status": "insufficient_context_fallback" if is_refusal else "verified_answer",
            "crag_score": eval_res["score"],
            "crag_reason": eval_res["reason"],
            "route": "rag_qa_fallback" if is_refusal else "rag_qa",
        }

    # ── CRAG failed (low quality context) ────────────────────────────────────
    print(
        f"[Orchestrator] CRAG failed (score={eval_res['score']:.3f}) — "
        f"falling back to General QA..."
    )
    gen_response = generate(prompt=user_message, mode="qa")
    fallback_msg = (
        "Note: This information is not available in the uploaded document. "
        "Answering from general knowledge:\n\n" + gen_response
    )
    return {
        "mode": "qa",
        "response": fallback_msg,
        "sources": sources,
        "crag_status": "insufficient_context_fallback",
        "crag_score": eval_res["score"],
        "crag_reason": eval_res["reason"],
        "route": "general_qa_fallback",
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

_DIAGRAM_NOISE = {
    "draw", "generate", "create", "make", "show", "build", "visualize",
    "visualise", "diagram", "chart", "flowchart", "flow", "graph",
    "sketch", "map", "layout", "graphviz", "a", "an", "the", "for",
    "of", "from", "my", "me", "please", "can", "you", "it", "this",
    "that", "about", "on", "to", "and", "with", "in", "document",
    "file", "upload", "uploaded", "pdf", "docx", "txt", "based",
    "using", "analyze", "analyse", "extract",
}


def _strip_diagram_keywords(msg: str) -> str:
    """Remove diagram/action words so we search by *topic* only."""
    words = msg.lower().split()
    remaining = [w for w in words if w not in _DIAGRAM_NOISE]
    return " ".join(remaining).strip()


def _strip_source_headers(context: str) -> str:
    """Remove [Document: ...] and [Source: ...] lines from context."""
    context = re.sub(r"^\[Document:.*?\]\s*\n?", "", context, flags=re.MULTILINE)
    context = re.sub(r"^\[Source:.*?\]\s*\n?", "", context, flags=re.MULTILINE)
    return context.strip()


def _build_context_from_chunks(chunks: list[dict], max_chars: int = 3000) -> str:
    """Assemble context string from chunks, preferring parent text."""
    context = ""
    seen = set()
    for c in chunks:
        text = c.get("parent_text") or c.get("text", "")
        key = text[:80]
        if key in seen:
            continue
        seen.add(key)
        part = f"[Source: {c.get('doc', '?')}, page {c.get('page', '?')}]\n{text}\n\n"
        if len(context) + len(part) > max_chars:
            break
        context += part
    return context.strip()
