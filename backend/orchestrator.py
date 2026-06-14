# orchestrator.py — brain of the system

import re

from router import route, detect_diagram_type, user_wants_doc_to_diagram
from rag import search_chunks, has_documents, get_all_content
from llm import generate, user_wants_doc_search, load_model, unload_model
from hyde import rewrite_query
from reranker import rerank
from crag import evaluate


def handle_request(user_message: str):
    """
    Advanced Orchestrator with CRAG, HyDE, Reranker, and Token small-to-big chunking.
    """

    mode = route(user_message)
    diagram_type = detect_diagram_type(user_message)

    # ── DIAGRAM ─────────────────────────────────────
    if mode == "diagram":
        explicitly_from_doc = user_wants_doc_to_diagram(user_message)

        if explicitly_from_doc and not has_documents():
            return {
                "mode": "qa",
                "response": "No documents uploaded. Please upload a document first.",
            }

        context = ""
        if has_documents():
            if explicitly_from_doc:
                context = get_all_content(max_chars=3500)
            else:
                search_query = _strip_diagram_keywords(user_message) or user_message
                # HyDE rewrite query for diagram retrieval as well
                hyde_query = rewrite_query(search_query)
                chunks = search_chunks(hyde_query, top_k=8)
                context = ""
                for c in chunks:
                    context += f"[Source: {c['doc']}, page {c['page']}]\n{c['parent_text']}\n\n"

            if context:
                context = re.sub(r"^\[Document:.*?\]\s*\n?", "", context, flags=re.MULTILINE).strip()
                context = re.sub(r"^\[Source:.*?\]\s*\n?", "", context, flags=re.MULTILINE).strip()

        return {
            "mode": "diagram",
            "response": generate(
                prompt=user_message,
                mode=mode,
                diagram_type=diagram_type,
                context=context,
            ),
        }

    # ── QA FLOW (ADVANCED CRAG) ──────────────────────────
    if not has_documents():
        return {"mode": "qa", "response": generate(prompt=user_message, mode="qa")}

    # 1. HyDE Query Rewriting (uses chat model)
    print(f"[Orchestrator] Rewriting query using HyDE...")
    hyde_query = rewrite_query(user_message)
    print(f"[Orchestrator] HyDE Query: {hyde_query[:100]}...")

    # Unload chat model before FAISS search to free memory
    unload_model()

    # 2. FAISS Retrieval (top 10 — reduced from 20 to save memory)
    print(f"[Orchestrator] Retrieving top-10 chunks from FAISS...")
    chunks = search_chunks(hyde_query, top_k=10)

    # 3. BGE Reranker (top 5) — uses dedicated reranker model, not chat model
    print(f"[Orchestrator] Reranking chunks...")
    reranked_chunks = rerank(user_message, chunks, top_k=5)

    # 4. CRAG Evaluation
    print(f"[Orchestrator] Evaluating chunks with CRAG...")
    eval_res = evaluate(user_message, reranked_chunks)

    sources = []
    for c in reranked_chunks:
        sources.append({
            "doc": c["doc"],
            "page": c["page"],
            "score": round(c.get("rerank_score", c.get("faiss_score", 0.0)), 4)
        })

    # If chunks pass evaluation, generate context-only answer
    if eval_res["pass"]:
        print(f"[Orchestrator] CRAG passed. Generating strict context-based answer...")
        response = generate(
            prompt=user_message,
            mode="doc_qa",
            context=eval_res["context"],
            confidence=eval_res["score"]
        )
        
        # Check if the generated answer is a refusal
        # (the model might say "The document does not contain sufficient information...")
        refusal_keywords = [
            "does not contain sufficient information",
            "do not contain specific information",
            "insufficient information",
            "no information",
            "not mentioned in the context"
        ]
        is_refusal = any(kw in response.lower() for kw in refusal_keywords)
        
        return {
            "mode": "qa",
            "response": response,
            "sources": sources,
            "crag_status": "insufficient_context" if is_refusal else "verified_answer",
            "crag_score": eval_res["score"],
            "crag_reason": eval_res["reason"]
        }
    else:
        print(f"[Orchestrator] CRAG failed. Returning refusal.")
        refusal = "The document does not contain sufficient information to answer this."
        return {
            "mode": "qa",
            "response": refusal,
            "sources": sources,
            "crag_status": "insufficient_context",
            "crag_score": eval_res["score"],
            "crag_reason": eval_res["reason"]
        }


# ── Helpers ─────────────────────────────────────────────────────────────
_DIAGRAM_NOISE = {
    "draw", "generate", "create", "make", "show", "build", "visualize",
    "visualise", "diagram", "chart", "flowchart", "flow", "graph",
    "sketch", "map", "layout", "mermaid", "a", "an", "the", "for",
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
