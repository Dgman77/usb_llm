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
    "flowchart TD": """Output ONLY a Mermaid flowchart code block. Nothing else.
Start with ```mermaid, end with ```.

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
    "sequenceDiagram": """Output ONLY a Mermaid sequenceDiagram block. Nothing else.
Start with ```mermaid, end with ```.

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
    "classDiagram": """Output ONLY a Mermaid classDiagram block. Nothing else.
Start with ```mermaid, end with ```.

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
    "stateDiagram-v2": """Output ONLY a Mermaid stateDiagram-v2 block. Nothing else.
Start with ```mermaid, end with ```.

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
}

GENERAL_SYSTEM = """You are a helpful AI assistant.
Answer clearly and concisely in under 200 words.
If unsure, say you don't know.
"""

DOC_SYSTEM = """You are a reading assistant.
Answer using ONLY the document excerpts provided.
If not found say: 'The uploaded document does not cover this topic.'
Mention the document name the answer came from.
"""

DOC_DIAGRAM_SYSTEM = """You are a document analysis and diagram generator.

TASK: First analyze the document content, then create a Mermaid diagram from it.

Step 1 - ANALYSIS: Extract from the document:
- Key entities (actors, objects, modules)
- Main processes or steps
- Decisions and conditions
- Relationships between entities
- Flow direction (who interacts with whom)

Step 2 - DIAGRAM: Create a Mermaid diagram that represents:
- For processes/flows: flowchart TD
- For sequences: sequenceDiagram  
- For data/tables: erDiagram
- For classes: classDiagram
- For states: stateDiagram-v2

IMPORTANT: 
- Use ONLY information from the document
- If document mentions "user", "customer", "admin" → add as nodes
- If document mentions create/read/update/delete → add as process steps
- If document shows relationships → add arrows

Output ONLY the Mermaid code block starting with ```mermaid and ending with ```.
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
    """Check if text contains a valid Mermaid block."""
    lower = text.lower()
    has_fence = "```mermaid" in lower or "```" in lower
    has_syntax = any(s in lower for s in MERMAID_STARTERS)
    return has_fence and has_syntax


def _extract_or_fix(text: str) -> str:
    """
    Try to extract mermaid block.
    If model forgot the fences, wrap it automatically.
    """
    # Already has ```mermaid fence
    m = re.search(r"```mermaid\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        return "```mermaid\n" + m.group(1).strip() + "\n```"

    # Has ``` fence but no mermaid label
    m = re.search(
        r"```\s*(flowchart|graph|sequenceDiagram|erDiagram|classDiagram|stateDiagram)([\s\S]*?)```",
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
                f"<|assistant|>\n```mermaid\n"
            )
        else:
            system = DIAGRAM_PROMPTS.get(diagram_type, DIAGRAM_PROMPTS["flowchart TD"])
            full_prompt = (
                f"<|system|>\n{system}<|end|>\n"
                f"<|user|>\n{prompt}<|end|>\n"
                f"<|assistant|>\n```mermaid\n"
            )

        result = llm(
            full_prompt,
            max_tokens=512,
            temperature=0.1,
            stop=["<|end|>", "<|user|>"],
            echo=False,
        )
        output = "```mermaid\n" + result["choices"][0]["text"].strip()

        # Improvement 2: validate — retry once if invalid
        if not _is_valid_mermaid(output):
            print("[LLM] Invalid Mermaid output — retrying...")
            result2 = llm(
                full_prompt,
                max_tokens=512,
                temperature=0.3,
                stop=["<|end|>", "<|user|>"],
                echo=False,
            )
            output2 = "```mermaid\n" + result2["choices"][0]["text"].strip()
            output = output2 if _is_valid_mermaid(output2) else output

        return _extract_or_fix(output)

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
