# orchestrator.py — brain of the system

import re

from router import route, detect_diagram_type, user_wants_doc_to_diagram
from rag import search, has_documents
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

        # If documents exist, search for relevant content
        context = ""
        if has_documents():
            # Use more chunks for document diagrams to get better coverage
            top_k = 12 if explicitly_from_doc else 6
            context = search(user_message, top_k=top_k)

            # Clean metadata for diagram context (avoid "[Document:...]" in nodes)
            context = re.sub(
                r"^\[Document:.*?\]\s*\n?", "", context, flags=re.MULTILINE
            ).strip()

            # User explicitly requested document-based diagram but no relevant content
            if explicitly_from_doc and not context:
                return {
                    "mode": "qa",
                    "response": "No relevant content found in uploaded documents. Try uploading a document first, or ask for a general diagram without mentioning the document.",
                }

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
