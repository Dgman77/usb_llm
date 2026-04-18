"""
llm.py — AI model loader and diagram/QA generator.

Improvements applied:
  1. Smarter prompt: 3 concrete Mermaid examples per diagram type
  2. Output validator: checks Mermaid syntax, retries once if invalid
  3. Diagram type routing: uses correct syntax (flowchart/sequence/er/class/state)
"""

import os
import glob
import re
from llama_cpp import Llama

USB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(USB_ROOT, "models")


# ── Model finder ───────────────────────────────────────────────────────────────


def find_model() -> str:
    path_file = os.path.join(MODELS_DIR, "model_path.txt")
    if os.path.exists(path_file):
        with open(path_file, "r", encoding="utf-8") as f:
            saved = f.read().strip().strip('"').strip()
        if os.path.exists(saved):
            print(f"[LLM] Model  : {os.path.basename(saved)}")
            return saved
    gguf_files = glob.glob(os.path.join(MODELS_DIR, "*.gguf"))
    if gguf_files:
        chosen = sorted(gguf_files)[0]
        print(f"[LLM] Model  : {os.path.basename(chosen)}")
        return chosen
    for folder in [
        r"D:\models",
        r"D:\model",
        r"E:\models",
        r"C:\models",
        os.path.expanduser("~/Downloads"),
    ]:
        hits = glob.glob(os.path.join(folder, "*.gguf"))
        if hits:
            chosen = hits[0]
            print(f"[LLM] Model  : {os.path.basename(chosen)}")
            os.makedirs(MODELS_DIR, exist_ok=True)
            with open(path_file, "w", encoding="utf-8") as f:
                f.write(chosen)
            return chosen
    raise FileNotFoundError(
        f"\n  No .gguf model found in: {MODELS_DIR}\n"
        "  Drop any .gguf file into models\\ and restart.\n"
    )


def get_model_name() -> str:
    try:
        return os.path.basename(find_model())
    except Exception:
        return "No model loaded"


def user_wants_doc_search(message: str) -> bool:
    doc_keywords = [
        "document",
        "pdf",
        "upload",
        "from the document",
        "in the document",
        "based on",
        "according to",
        "from uploaded",
        "from my file",
    ]
    msg = message.lower()
    return any(kw in msg for kw in doc_keywords)


_llm = None
_llm_path = None


def load_model():
    global _llm, _llm_path
    current = find_model()
    if _llm is not None and _llm_path == current:
        return _llm
    if _llm_path and _llm_path != current:
        print(f"[LLM] Switching → {os.path.basename(current)}")
    else:
        print("[LLM] Loading model (30-60s)...")
    _llm = Llama(
        model_path=current,
        n_ctx=4096,
        n_threads=max(4, os.cpu_count() or 4),
        n_batch=256,
        use_mmap=True,
        use_mlock=False,
        verbose=False,
    )
    _llm_path = current
    print(f"[LLM] Ready — {os.path.basename(current)}")
    return _llm


# ── Improvement 1: Diagram prompts with 3 examples each ───────────────────────

DIAGRAM_PROMPTS = {
    "flowchart TD": """Output ONLY a Mermaid flowchart code block. NO explanation before or after. Start with ```mermaid, end with ```.

Example 1 — login flow:
```mermaid
flowchart TD
    A[Open app] --> B{Logged in?}
    B -- Yes --> C[Dashboard]
    B -- No --> D[Login page]
    D --> E[Enter credentials]
    E --> F{Valid?}
    F -- Yes --> C
    F -- No --> D
```

Example 2 — order process:
```mermaid
flowchart TD
    A[Place order] --> B[Payment]
    B --> C{Payment OK?}
    C -- Yes --> D[Confirm order]
    C -- No --> E[Retry payment]
    D --> F[Ship item]
    F --> G[Delivered]
```

Example 3 — CI/CD pipeline:
```mermaid
flowchart TD
    A[Push code] --> B[Run tests]
    B --> C{Tests pass?}
    C -- Yes --> D[Build image]
    C -- No --> E[Notify dev]
    D --> F[Deploy staging]
    F --> G[Deploy prod]
```
Now generate a flowchart for:""",
    "sequenceDiagram": """Output ONLY a Mermaid sequenceDiagram code block. NO explanation before or after. Start with ```mermaid, end with ```.

Example 1 — login API:
```mermaid
sequenceDiagram
    Browser->>Server: POST /login
    Server->>DB: Check credentials
    DB-->>Server: User found
    Server-->>Browser: JWT token
```

Example 2 — payment:
```mermaid
sequenceDiagram
    App->>PaymentGateway: Charge request
    PaymentGateway->>Bank: Authorize
    Bank-->>PaymentGateway: Approved
    PaymentGateway-->>App: Success
```

Example 3 — file upload:
```mermaid
sequenceDiagram
    Client->>API: Upload file
    API->>Storage: Save file
    Storage-->>API: File URL
    API-->>Client: 200 OK + URL
```
Now generate a sequence diagram for:""",
    "erDiagram": """Output ONLY a Mermaid erDiagram block. Nothing else.
Start with ```mermaid, end with ```.

Example 1 — blog:
```mermaid
erDiagram
    USER ||--o{ POST : writes
    POST ||--o{ COMMENT : has
    USER {
        int id PK
        string name
        string email
    }
    POST {
        int id PK
        int user_id FK
        string title
        string content
    }
```

Example 2 — e-commerce:
```mermaid
erDiagram
    CUSTOMER ||--o{ ORDER : places
    ORDER ||--|{ ORDER_ITEM : contains
    PRODUCT ||--o{ ORDER_ITEM : included_in
```

Example 3 — school:
```mermaid
erDiagram
    STUDENT ||--o{ ENROLLMENT : has
    COURSE ||--o{ ENROLLMENT : has
    TEACHER ||--o{ COURSE : teaches
```
Now generate an ER diagram for:""",
    "classDiagram": """Output ONLY a Mermaid classDiagram code block. NO explanation before or after. Start with ```mermaid, end with ```.

Example 1 — animals:
```mermaid
classDiagram
    Animal <|-- Dog
    Animal <|-- Cat
    Animal : +String name
    Animal : +makeSound()
    Dog : +fetch()
    Cat : +purr()
```

Example 2 — vehicles:
```mermaid
classDiagram
    Vehicle <|-- Car
    Vehicle <|-- Truck
    Vehicle : +String model
    Vehicle : +start()
    Car : +int seats
    Truck : +int payload
```
Now generate a class diagram for:""",
    "stateDiagram-v2": """Output ONLY a Mermaid stateDiagram-v2 code block. NO explanation before or after. Start with ```mermaid, end with ```.

Example 1 — order:
```mermaid
stateDiagram-v2
    [*] --> Pending
    Pending --> Processing : payment received
    Processing --> Shipped : packed
    Shipped --> Delivered : arrived
    Delivered --> [*]
```

Example 2 — traffic light:
```mermaid
stateDiagram-v2
    [*] --> Red
    Red --> Green : timer
    Green --> Yellow : timer
    Yellow --> Red : timer
```
Now generate a state diagram for:""",
    "gantt": """Output ONLY a Mermaid gantt chart code block. NO explanation before or after. Start with ```mermaid, end with ```.

Example 1 — software project:
```mermaid
gantt
    title Software Development
    dateFormat  YYYY-MM-DD
    section Planning
    Requirements      :a1, 2024-01-01, 10d
    Design           :a2, after a1, 7d
    section Implementation
    Backend          :b1, after a2, 14d
    Frontend         :b2, after a2, 12d
    section Testing
    Integration      :c1, after b1, 5d
    UAT              :c2, after b1, 5d
```

Example 2 — construction:
```mermaid
gantt
    title Building House
    dateFormat  YYYY-MM-DD
    section Foundation
    Excavation      :f1, 2024-01-01, 5d
    Concrete        :f2, after f1, 3d
    section Frame
    Framing         :f3, after f2, 10d
    Roofing         :f4, after f3, 5d
```
Now generate a Gantt chart for:""",
    "pie": """Output ONLY a Mermaid pie chart code block. NO explanation before or after. Start with ```mermaid, end with ```.

Example 1 — market share:
```mermaid
pie title Market Share
    "Company A" : 35
    "Company B" : 25
    "Company C" : 20
    "Others" : 20
```

Example 2 — budget allocation:
```mermaid
pie title Budget 2024
    "Development" : 40
    "Marketing" : 25
    "Operations" : 20
    "Admin" : 15
```
Now generate a pie chart for:""",
    "mindmap": """Output ONLY a Mermaid mindmap code block. NO explanation before or after. Start with ```mermaid, end with ```.

Example 1 — project planning:
```mermaid
mindmap
  root((Project X))
    Planning
      Requirements
      Timeline
      Resources
    Development
      Backend
      Frontend
      Database
    Testing
      Unit Tests
      Integration
    Deployment
      Staging
      Production
```

Example 2 — problem analysis:
```mermaid
mindmap
  root((System Issue))
    Symptoms
      Slow response
      Timeouts
      Errors
    Causes
      Network latency
      CPU spike
      Memory leak
    Solutions
      Optimize queries
      Scale hardware
      Patch bug
```
Now generate a mindmap for:""",
}

GENERAL_SYSTEM = """You are a helpful AI assistant.

STRUCTURE YOUR RESPONSE as follows:
1. First: A brief paragraph (2-3 sentences) summarizing the answer
2. Then: Point-by-point details using bullet points if applicable

Answer clearly and concisely in under 200 words.
If unsure, say you don't know.
"""

DOC_SYSTEM = """You are a reading assistant.

STRUCTURE YOUR RESPONSE as follows:
1. First: A brief paragraph (2-3 sentences) summarizing the answer based on the document
2. Then: Point-by-point details using bullet points if applicable

Answer using ONLY the document excerpts provided.
If not found say: 'The uploaded document does not cover this topic.'
Mention the document name the answer came from.
"""

DOC_DIAGRAM_SYSTEM = """You are a document analysis and diagram generator.

TASK: Analyze the document content and create a Mermaid diagram that accurately represents the information.

STEP 1 - EXTRACT from the document:
• Entities: people, systems, modules, components, roles (e.g., user, admin, server)
• Processes: actions, operations, workflows (e.g., create, validate, process)
• Decisions: conditional logic, branches, checkpoints
• Relationships: connections, dependencies, ownership, flows
• Data structures: tables, fields, schemas (for ER diagrams)
• States: lifecycle stages, status changes (for state diagrams)
• Interactions: messages, calls, requests (for sequence diagrams)

STEP 2 - CHOOSE diagram type based on content:
• flowchart TD → processes, workflows, system architecture, data flow
• sequenceDiagram → message sequences, API calls, step-by-step interactions
• erDiagram → database tables, data models, entity relationships
• classDiagram → object-oriented structures, classes with attributes/methods
• stateDiagram-v2 → state machines, lifecycles, status transitions

STEP 3 - BUILD the diagram:
• Include ALL key entities from the document
• Show DIRECTION of flow (--> or --->)
• Add MEANINGFUL labels on arrows describing the action
• Use SQUARE BRACKETS for nodes: NodeName[Label]
• Keep node labels concise (3-5 words max)
• Group related steps with subgraphs if helpful

CRITICAL RULES:
✗ DO NOT invent information not in the document
✓ ONLY use facts from the provided document excerpts
✓ If document mentions "user logs in" → include user, login, authentication nodes
✓ If document shows data flow → trace the complete path
✓ If document describes multiple scenarios → choose the most important one

OUTPUT FORMAT:
Return ONLY the Mermaid code block. No explanations.
```mermaid
<diagram code here>
```
"""


# ── Improvement 2: Output validator ───────────────────────────────────────────

MERMAID_STARTERS = [
    "flowchart",
    "graph ",
    "sequencediagram",
    "erdiagram",
    "classdiagram",
    "statediagram",
    "gantt",
    "pie",
    "mindmap",
]


def _is_valid_mermaid(text: str) -> bool:
    """Check if text contains a valid Mermaid diagram."""
    lower = text.lower()
    # Must have mermaid code block or at least diagram syntax
    has_mermaid_fence = "```mermaid" in lower
    has_any_fence = "```" in lower
    # Check for any valid Mermaid diagram type
    has_diagram_type = any(
        re.search(rf"\b{re.escape(starter)}\b", lower)
        for starter in [
            "flowchart",
            "graph ",
            "sequencediagram",
            "erdiagram",
            "classdiagram",
            "statediagram",
            "gantt",
            "pie",
            "mindmap",
        ]
    )
    # Accept if has mermaid fence + diagram, OR any fence + diagram (implied mermaid)
    return (has_mermaid_fence and has_diagram_type) or (
        has_any_fence and has_diagram_type
    )


def _extract_or_fix(text: str) -> str:
    """
    Try to extract mermaid block.
    If model forgot the fences, wrap it automatically.
    """
    # Already has ```mermaid fence
    m = re.search(r"```mermaid\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        return "```mermaid\n" + m.group(1).strip() + "\n```"

    # Has ``` fence but no mermaid label - match any diagram type
    m = re.search(
        r"```\s*(flowchart|graph|sequenceDiagram|erDiagram|classDiagram|stateDiagram|stateDiagram-v2|gantt|pie|mindmap)([\s\S]*?)```",
        text,
        re.IGNORECASE,
    )
    if m:
        return "```mermaid\n" + m.group(1) + m.group(2).strip() + "\n```"

    # No fence but starts with diagram keyword — wrap it
    stripped = text.strip()
    for starter in [
        "flowchart",
        "graph ",
        "sequenceDiagram",
        "erDiagram",
        "classDiagram",
        "stateDiagram",
        "stateDiagram-v2",
        "gantt",
        "pie",
        "mindmap",
    ]:
        if stripped.lower().startswith(starter.lower()):
            return "```mermaid\n" + stripped + "\n```"

    return text  # give up, return as-is


# ── Generate ───────────────────────────────────────────────────────────────────


def generate(
    prompt: str, mode: str, context: str = "", diagram_type: str = "flowchart TD"
) -> str:
    llm = load_model()

    # ── Diagram ───────────────────────────────────────────────────────────────
    if mode == "diagram":
        if context:
            context = context[:4096]
            full_prompt = (
                f"<|system|>\n{DOC_DIAGRAM_SYSTEM}<|end|>\n"
                f"<|user|>\n"
                f"=== DOCUMENT CONTENT ===\n{context}\n=== END ===\n\n"
                f"User request: {prompt}\n"
                f"Extract key information from the document above and create a {diagram_type} diagram.\n"
                f"<|end|>\n"
                f"<|assistant|>\n"
            )
        else:
            system = DIAGRAM_PROMPTS.get(diagram_type, DIAGRAM_PROMPTS["flowchart TD"])
            full_prompt = (
                f"<|system|>\n{system}<|end|>\n"
                f"<|user|>\n{prompt}<|end|>\n"
                f"<|assistant|>\n"
            )

        # Adjust generation parameters based on whether we have context
        temp = 0.05 if context else 0.15
        max_tokens = 768 if context else 512

        result = llm(
            full_prompt,
            max_tokens=max_tokens,
            temperature=temp,
            stop=["<|end|>", "<|user|>"],
            echo=False,
        )
        raw_output = result["choices"][0]["text"].strip()
        extracted = _extract_or_fix(raw_output)

        # Validate — retry up to 2 times if invalid
        if not _is_valid_mermaid(extracted):
            print("[LLM] Invalid Mermaid output — retrying...")
            for attempt in range(2):
                result2 = llm(
                    full_prompt,
                    max_tokens=max_tokens,
                    temperature=0.25,
                    stop=["<|end|>", "<|user|>"],
                    echo=False,
                )
                raw_output2 = result2["choices"][0]["text"].strip()
                extracted2 = _extract_or_fix(raw_output2)
                if _is_valid_mermaid(extracted2):
                    return extracted2
            # All retries failed, return best attempt
            print("[LLM] All retries produced invalid Mermaid")

        return extracted

    # ── Q&A with documents ────────────────────────────────────────────────────
    if context:
        context = context[:4096]
        full_prompt = (
            f"<|system|>\n{DOC_SYSTEM}<|end|>\n"
            f"<|user|>\n"
            f"=== DOCUMENT EXCERPTS ===\n{context}\n=== END ===\n\n"
            f"Using ONLY the excerpts above, answer: {prompt}\n"
            f"<|end|>\n"
            f"<|assistant|>\nBased on the uploaded document: "
        )
        result = llm(
            full_prompt,
            max_tokens=512,
            temperature=0.2,
            stop=["<|end|>", "<|user|>"],
            echo=False,
        )
        answer = result["choices"][0]["text"].strip()
        if not answer.lower().startswith("based on"):
            answer = "Based on the uploaded document: " + answer
        return answer

    # ── General Q&A ───────────────────────────────────────────────────────────
    full_prompt = (
        f"<|system|>\n{GENERAL_SYSTEM}<|end|>\n"
        f"<|user|>\n{prompt}<|end|>\n"
        f"<|assistant|>\n"
    )
    result = llm(
        full_prompt,
        max_tokens=512,
        temperature=0.2,
        stop=["<|end|>", "<|user|>"],
        echo=False,
    )
    return result["choices"][0]["text"].strip()
