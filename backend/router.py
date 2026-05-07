"""
router.py — detects diagram vs Q&A AND which diagram type.
Improvement 3: returns diagram subtype so llm.py uses the right Mermaid syntax.
Improvement 4: detects document-to-diagram requests (e.g., "draw from my document")
"""

import re

# Maps keywords → Mermaid diagram type
DIAGRAM_TYPES = {
    "sequenceDiagram": [
        "sequence",
        "api call",
        "request response",
        "client server",
        "communication",
        "message",
        "sends to",
        "calls",
        "interaction",
    ],
    "erDiagram": [
        "database",
        "schema",
        "erd",
        "entity",
        "table",
        "relation",
        "sql",
        "db design",
        "data model",
        "relationship",
    ],
    "classDiagram": [
        "class",
        "object",
        "inheritance",
        "oop",
        "uml class",
        "interface",
        "extends",
        "implements",
        "method",
        "attribute",
    ],
    "stateDiagram-v2": [
        "state",
        "transition",
        "status",
        "lifecycle",
        "state machine",
        "states",
        "workflow state",
    ],
    "gantt": [
        "gantt",
        "timeline",
        "schedule",
        "project plan",
        "milestone",
        "deadline",
        "duration",
        "phase",
    ],
    "pie": [
        "pie chart",
        "distribution",
        "percentage",
        "breakdown",
        "proportion",
        "statistics",
        "data distribution",
    ],
    "mindmap": [
        "mindmap",
        "mind map",
        "brainstorm",
        "idea",
        "concept",
        "central idea",
        "branches",
    ],
    "flowchart TD": [
        "draw",
        "flowchart",
        "flow",
        "process",
        "pipeline",
        "steps",
        "diagram",
        "chart",
        "architecture",
        "visualize",
        "visualise",
        "map",
        "graph",
        "sketch",
        "mermaid",
        "layout",
        "structure",
        "system design",
        "data flow",
        "process flow",
        "design",
        "show me",
        "diagram of",
    ],
}

# Flat list for fast diagram detection
ALL_DIAGRAM_KEYWORDS = [kw for kws in DIAGRAM_TYPES.values() for kw in kws]

# Keywords indicating user wants to generate diagram FROM uploaded document
DOC_TO_DIAGRAM_KEYWORDS = [
    "from the document",
    "from my document",
    "from my file",
    "from uploaded",
    "from the uploaded",
    "from the file",
    "from the pdf",
    "from my pdf",
    "based on the document",
    "based on document",
    "based on the file",
    "based on my file",
    "based on the pdf",
    "based on uploaded",
    "using the document",
    "using my document",
    "using the file",
    "using my file",
    "analyze the document",
    "analyse the document",
    "analyze the file",
    "analyse the file",
    "analyze my document",
    "analyse my document",
    "diagram from",
    "draw from",
    "flowchart from",
    "chart from",
    "schema from",
    "er diagram from",
    "extract from",
    "visualize the document",
    "visualise the document",
    "visualize the file",
    "visualise the file",
    "visualize my",
    "visualise my",
    "diagram of the document",
    "diagram of my document",
    "diagram of my file",
    "diagram of the file",
    "chart of the document",
    "chart of my",
    "graph of the document",
    "graph of my",
    "map the document",
    "map my document",
    "summarize as diagram",
    "summarise as diagram",
    "convert to diagram",
    "turn into diagram",
    "turn into flowchart",
    "make a diagram of",
    "create a diagram of",
    "generate a diagram of",
    "generate diagram of",
    "draw a diagram of",
    "of the uploaded",
    "of my uploaded",
]


def user_wants_doc_to_diagram(user_message: str) -> bool:
    """Check if user wants to generate a diagram FROM an uploaded document."""
    msg = user_message.lower().strip()

    # First check for document-to-diagram keywords
    for kw in DOC_TO_DIAGRAM_KEYWORDS:
        if kw in msg:
            return True

    # Also check if "diagram" is requested AND user mentions "document"/"file"/"upload"
    diagram_requested = any(kw in msg for kw in ALL_DIAGRAM_KEYWORDS)
    doc_reference = any(
        kw in msg
        for kw in [
            "document", "file", "upload", "uploaded", "pdf", "docx",
            "txt", "knowledge", "external", "attachment",
        ]
    )
    return diagram_requested and doc_reference


def route(user_message: str) -> str:
    """Returns 'diagram' or 'qa'."""
    msg = user_message.lower().strip()
    for kw in ALL_DIAGRAM_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", msg):
            return "diagram"
    return "qa"


def detect_diagram_type(user_message: str) -> str:
    """
    Returns the best Mermaid diagram type for this request.
    Improvement 3: tells llm.py exactly which syntax to use.
    """
    msg = user_message.lower().strip()
    # Check specific types first (flowchart is the fallback)
    for dtype, keywords in DIAGRAM_TYPES.items():
        if dtype == "flowchart TD":
            continue  # check this last
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", msg):
                return dtype
    return "flowchart TD"
