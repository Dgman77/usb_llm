# orchestrator.py — brain of the system

import re

from router import route, detect_diagram_type, user_wants_doc_to_diagram
from rag import search_adaptive, has_documents, get_all_content
from llm import generate, user_wants_doc_search


def handle_request(user_message: str):
    """
    Adaptive Orchestrator:
    - High Confidence: Strict source-based answer.
    - Low Confidence: Related data fallback or general knowledge.
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
                search_query = _strip_diagram_keywords(user_message)
                # Use adaptive search for diagrams too to find the best section
                res = search_adaptive(search_query or user_message, top_k=8)
                context = res["context"]

            if context:
                context = re.sub(r"^\[Document:.*?\]\s*\n?", "", context, flags=re.MULTILINE).strip()

        return {
            "mode": "diagram",
            "response": generate(
                prompt=user_message,
                mode=mode,
                diagram_type=diagram_type,
                context=context,
            ),
        }

    # ── QA FLOW (ADAPTIVE) ──────────────────────────
    if not has_documents():
        return {"mode": "qa", "response": generate(prompt=user_message, mode="qa")}

    # Perform Adaptive Search
    search_res = search_adaptive(user_message)
    context = search_res["context"]
    confidence = search_res["confidence"]
    suggestion = search_res["suggestion"]

    # CASE 1: User explicitly asked about documents
    if user_wants_doc_search(user_message):
        # Even if confidence is low, we try to answer from doc if they asked
        return {
            "mode": "qa",
            "response": generate(
                prompt=user_message, 
                mode="doc_qa", 
                context=context, 
                confidence=confidence
            ),
            "sources": search_res["sources"]
        }

    # CASE 2: High Confidence -> Source-accurate answer
    if confidence > 0.6:
        return {
            "mode": "qa",
            "response": generate(prompt=user_message, mode="doc_qa", context=context),
            "sources": search_res["sources"]
        }

    # CASE 3: Medium/Low Confidence -> Fallback to general + related info
    general_answer = generate(prompt=user_message, mode="qa")
    
    if suggestion:
        # Append related info hint to general answer
        response = f"{general_answer}\n\n---\n**Related info from your files:**\n{suggestion}"
        return {"mode": "qa", "response": response, "sources": search_res["sources"]}

    return {"mode": "qa", "response": general_answer}


# ── Helpers ─────────────────────────────────────────────────────────────
# Words that indicate "I want a diagram" but carry no topical meaning
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
