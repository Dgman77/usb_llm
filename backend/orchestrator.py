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

    # FIX-2: General Query Routing Precheck
    # 1. Use already-resident embed model (no load needed)
    from llm import get_embed_model
    embed_model = get_embed_model()
    
    # 2. Embed raw query (no HyDE)
    try:
        q_res = embed_model.create_embedding(user_message)
        query_embedding = q_res["data"][0]["embedding"]
    except Exception as e:
        print(f"[Orchestrator] Precheck embedding failed: {e}")
        query_embedding = None

    if query_embedding is not None:
        # 3. FAISS search top-3 only
        precheck_chunks = search_chunks(user_message, top_k=3)
        
        # 4. Run CRAG heuristic on those 3 chunks
        for c in precheck_chunks:
            c["rerank_score"] = c.get("faiss_score", 0.0)
            
        from rag import _chunks, _embeddings
        precheck_embeddings = []
        for c in precheck_chunks:
            try:
                idx = _chunks.index(c["text"])
                precheck_embeddings.append(_embeddings[idx])
            except ValueError:
                try:
                    res = embed_model.create_embedding(c["text"])
                    precheck_embeddings.append(res["data"][0]["embedding"])
                except Exception:
                    precheck_embeddings.append([0.0] * len(query_embedding))
                    
        precheck_eval = evaluate(user_message, query_embedding, precheck_chunks, precheck_embeddings)
        
        # 5. If CRAG score < 0.15 → route to general LLM directly (skip HyDE, full RAG)
        if precheck_eval["score"] < 0.15:
            print(f"[Orchestrator] Precheck failed (score {precheck_eval['score']} < 0.15). Routing to general LLM.")
            return {"mode": "qa", "response": generate(prompt=user_message, mode="qa")}
        else:
            print(f"[Orchestrator] Precheck passed (score {precheck_eval['score']} >= 0.15). Proceeding with full RAG.")

    # 1. HyDE Query Rewriting (uses chat model)
    print(f"[Orchestrator] Rewriting query using HyDE...")
    hyde_query = rewrite_query(user_message)
    print(f"[Orchestrator] HyDE Query: {hyde_query[:100]}...")

    # Unload chat model before FAISS search to free memory (if chat_only strategy)
    unload_model()

    # 2. FAISS Retrieval (top 10 — reduced from 20 to save memory)
    print(f"[Orchestrator] Retrieving top-10 chunks from FAISS...")
    chunks = search_chunks(hyde_query, top_k=10)

    # 3. BGE Reranker (top 5) — uses dedicated reranker model, not chat model
    print(f"[Orchestrator] Reranking chunks...")
    reranked_chunks = rerank(user_message, chunks, top_k=5)

    # If query embedding was not generated, generate it now
    if query_embedding is None:
        try:
            q_res = embed_model.create_embedding(user_message)
            query_embedding = q_res["data"][0]["embedding"]
        except Exception:
            query_embedding = [0.0] * 768

    # 4. CRAG Evaluation
    print(f"[Orchestrator] Evaluating chunks with CRAG...")
    from rag import _chunks, _embeddings
    reranked_embeddings = []
    for c in reranked_chunks:
        try:
            idx = _chunks.index(c["text"])
            reranked_embeddings.append(_embeddings[idx])
        except ValueError:
            try:
                res = embed_model.create_embedding(c["text"])
                reranked_embeddings.append(res["data"][0]["embedding"])
            except Exception:
                reranked_embeddings.append([0.0] * len(query_embedding))

    eval_res = evaluate(user_message, query_embedding, reranked_chunks, reranked_embeddings)

    # If blocked as out of domain (FIX-6 Part C), return immediately
    if eval_res.get("reason") == "out_of_domain":
        print(f"[Orchestrator] CRAG blocked query as out_of_domain.")
        return {
            "mode": "qa",
            "response": "This information is not available in the uploaded document.",
            "sources": [],
            "crag_score": eval_res["score"],
            "crag_status": "out_of_domain",
            "crag_reason": eval_res["reason"]
        }

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
        refusal_keywords = [
            "does not contain sufficient information",
            "do not contain specific information",
            "insufficient information",
            "no information",
            "not mentioned in the context",
            "this information is not available in the uploaded document"
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
        refusal = "This information is not available in the uploaded document."
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
