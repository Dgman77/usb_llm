# orchestrator.py — brain of the system

import re

from router import route, detect_diagram_type, user_wants_doc_to_diagram
from rag import search, has_documents, get_all_content
from llm import generate, user_wants_doc_search


def handle_request(user_message: str):
    """
    Decides:
    - diagram vs qa
    - doc vs general
    - document-to-diagram (generate diagram from uploaded document)
    - fallback logic
    """

    mode = route(user_message)
    diagram_type = detect_diagram_type(user_message)

    # ── DIAGRAM ─────────────────────────────────────
    if mode == "diagram":
        # Check if user explicitly wants to generate diagram FROM document
        explicitly_from_doc = user_wants_doc_to_diagram(user_message)

        # If user explicitly wants document-based diagram but no documents uploaded
        if explicitly_from_doc and not has_documents():
            return {
                "mode": "qa",
                "response": "No documents uploaded. Please upload a document first, then ask for a diagram from it.",
            }

        context = ""
        if has_documents():
            if explicitly_from_doc:
                # User explicitly wants diagram from document —
                # grab ALL document content for maximum coverage
                context = get_all_content(max_chars=3500)

                if not context:
                    return {
                        "mode": "qa",
                        "response": "No relevant content found in uploaded documents. Try uploading a document first, or ask for a general diagram without mentioning the document.",
                    }
            else:
                # User asked for a diagram and docs happen to be uploaded —
                # do a broad search to see if document content is relevant
                # Strip diagram keywords from query so we search by topic, not "draw flowchart"
                search_query = _strip_diagram_keywords(user_message)
                if search_query:
                    context = search(search_query, top_k=8)
                else:
                    # Query was purely diagram keywords — grab all doc content
                    context = get_all_content(max_chars=3500)

            # Clean metadata tags from context (avoid "[Document:...]" in diagram nodes)
            if context:
                context = re.sub(
                    r"^\[Document:.*?\]\s*\n?", "", context, flags=re.MULTILINE
                ).strip()

        # Generate diagram with or without context
        return {
            "mode": "diagram",
            "response": generate(
                prompt=user_message,
                mode=mode,
                diagram_type=diagram_type,
                context=context,
            ),
        }

    # ── QA FLOW ─────────────────────────────────────
    context = ""
    if has_documents():
        context = search(user_message)

    # CASE 1: user explicitly wants document
    if user_wants_doc_search(user_message):
        if not context:
            return {"mode": "qa", "response": "No documents uploaded."}

        return {
            "mode": "qa",
            "response": generate(prompt=user_message, mode="qa", context=context),
        }

    # CASE 2: normal answer first
    answer = generate(prompt=user_message, mode="qa")

    # CASE 3: fallback to RAG
    weak = ["i don't know", "not sure", "cannot", "no information"]

    if any(w in answer.lower() for w in weak) and context:
        answer = generate(prompt=user_message, mode="qa", context=context)

    return {"mode": "qa", "response": answer}


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
