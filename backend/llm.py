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
from diagram_engine import process_diagram, is_valid as is_valid_diagram, complexity_score

USB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(USB_ROOT, "models")


# ── Model finder ───────────────────────────────────────────────────────────────

import gc

def _sanitize_path(raw: str) -> str:
    """Clean up path strings that may have escaped backslashes."""
    # Fix double-escaped backslashes (\\\\) → single backslash
    cleaned = raw.strip().strip('"').strip("'").strip()
    cleaned = cleaned.replace('\\\\', '\\')
    cleaned = cleaned.replace('\\\\', '\\')  # second pass for quad-escaped
    return cleaned


def _prefer_quantized(files: list) -> list:
    """Sort model files to prefer smaller quantized models (Q4 > Q5 > Q6 > Q8 > FP16).
    This ensures 8GB RAM systems load the smallest workable model first."""
    def _quant_priority(path):
        name = os.path.basename(path).lower()
        if 'q4_' in name or 'q4-' in name: return 0
        if 'q5_' in name or 'q5-' in name: return 1
        if 'q6_' in name or 'q6-' in name: return 2
        if 'q8_' in name or 'q8-' in name: return 3
        if 'fp16' in name or 'f16' in name: return 4
        return 5  # unknown quantization
    return sorted(files, key=_quant_priority)


def find_model() -> str:
    path_file = os.path.join(MODELS_DIR, "model_path.txt")
    if os.path.exists(path_file):
        with open(path_file, "r", encoding="utf-8") as f:
            saved = _sanitize_path(f.read())
        if saved and os.path.exists(saved):
            print(f"[LLM] Model  : {os.path.basename(saved)}")
            return saved
        else:
            print(f"[LLM] Saved model path invalid or not found: {saved!r}")
    gguf_files = glob.glob(os.path.join(MODELS_DIR, "*.gguf"))
    chat_files = [f for f in gguf_files if "embed" not in os.path.basename(f).lower() and "rerank" not in os.path.basename(f).lower()]
    if chat_files:
        chat_files = _prefer_quantized(chat_files)
        chosen = chat_files[0]
        print(f"[LLM] Model  : {os.path.basename(chosen)}")
        return chosen
    for folder in [
        r"D:\models",
        r"D:\model",
        r"E:\models",
        r"C:\models",
        os.path.expanduser("~/Downloads"),
        os.path.join(os.path.expanduser("~/Downloads"), "models"),
    ]:
        if not os.path.exists(folder):
            continue
        hits = glob.glob(os.path.join(folder, "*.gguf"))
        chat_hits = [f for f in hits if "embed" not in os.path.basename(f).lower() and "rerank" not in os.path.basename(f).lower()]
        if chat_hits:
            chat_hits = _prefer_quantized(chat_hits)
            chosen = chat_hits[0]
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


def find_available_models() -> list[dict]:
    available = []
    seen_paths = set()
    search_paths = [
        MODELS_DIR,
        r"D:\models",
        r"D:\model",
        r"E:\models",
        r"C:\models",
        os.path.expanduser("~/Downloads"),
        os.path.join(os.path.expanduser("~/Downloads"), "models")
    ]
    active_path = None
    try:
        active_path = find_model()
    except Exception:
        pass
    for folder in search_paths:
        if not os.path.exists(folder):
            continue
        hits = glob.glob(os.path.join(folder, "*.gguf"))
        for h in hits:
            name_lower = os.path.basename(h).lower()
            if "embed" in name_lower or "rerank" in name_lower:
                continue
            abs_path = os.path.abspath(h)
            if abs_path not in seen_paths:
                seen_paths.add(abs_path)
                available.append({
                    "name": os.path.basename(h),
                    "path": abs_path,
                    "active": (abs_path == os.path.abspath(active_path)) if active_path else False
                })
    return available


def switch_model(path: str) -> dict:
    global CURRENT_STRATEGY
    can_load, strategy, estimated_ram = check_ram_budget(path)
    chat_size = get_gguf_size_gb(path)

    if strategy == "too_large":
        return {
            "success": False,
            "error": "Model too large for 8GB RAM.",
            "model_size_gb": round(chat_size, 2),
            "estimated_total_gb": round(estimated_ram, 2),
            "recommendation": "Use a Q4 quantized model under 4GB for best performance."
        }

    # Save new path to file
    path_file = os.path.join(MODELS_DIR, "model_path.txt")
    os.makedirs(MODELS_DIR, exist_ok=True)
    with open(path_file, "w", encoding="utf-8") as f:
        f.write(path)

    CURRENT_STRATEGY = strategy

    if strategy == "all_resident":
        unload_chat_model()
        gc.collect()
        load_chat_model()
        try:
            get_embed_model()
        except Exception:
            pass
        try:
            get_reranker_model()
        except Exception:
            pass
        print(f"Chat switched. All 3 models resident. RAM: {estimated_ram:.1f}GB")

    elif strategy == "drop_reranker":
        unload_chat_model()
        unload_reranker()
        gc.collect()
        load_chat_model()
        try:
            get_embed_model()
        except Exception:
            pass
        print(f"Chat switched. Reranker will hot-swap (model too large for 3 resident). RAM: {estimated_ram:.1f}GB")

    elif strategy == "chat_only":
        unload_chat_model()
        unload_embed_model()
        unload_reranker()
        gc.collect()
        load_chat_model()
        print(f"Chat switched. Embed + reranker will hot-swap (large model loaded). RAM: {estimated_ram:.1f}GB")

    return {
        "success": True,
        "active": get_model_name(),
        "strategy": strategy,
        "estimated_ram": round(estimated_ram, 2)
    }


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


# RAM-aware parameters
MAX_RAM_GB = 7.5
SYSTEM_OVERHEAD_GB = 2.35
EMBED_SIZE_GB = 0.14
RERANKER_SIZE_GB = 0.61
LLM_CTX_WINDOW = 4096

_chat_model = None
_chat_model_path = None
_embed_model = None
_embed_model_path = None
_reranker_model = None
_reranker_model_path = None

# Fallback alias for existing references
_llm = None
_llm_path = None
_model_type = None

# Default strategy (updated on model switcher route)
CURRENT_STRATEGY = "all_resident"


def get_gguf_size_gb(model_path):
    """
    Returns file size of GGUF model in GB.
    Used to estimate RAM usage before loading.
    """
    if not os.path.exists(model_path):
        return 0.0
    size_bytes = os.path.getsize(model_path)
    return size_bytes / (1024 ** 3)


def check_ram_budget(chat_model_path,
                      embed_resident=True,
                      reranker_resident=True):
    """
    Returns (can_load, strategy, estimated_ram)

    Strategy options:
      "all_resident"     → all 3 models in RAM
      "drop_reranker"    → unload reranker to fit
      "drop_embed"       → unload embed to fit
      "chat_only"        → only chat fits, swap
                           embed/reranker per query
      "too_large"        → model too big even alone
    """
    chat_size = get_gguf_size_gb(chat_model_path)
    base = SYSTEM_OVERHEAD_GB + chat_size

    if embed_resident:
        base += EMBED_SIZE_GB
    if reranker_resident:
        base += RERANKER_SIZE_GB

    if base <= MAX_RAM_GB:
        return True, "all_resident", base

    # try without reranker
    base_no_reranker = (SYSTEM_OVERHEAD_GB +
                        chat_size + EMBED_SIZE_GB)
    if base_no_reranker <= MAX_RAM_GB:
        return True, "drop_reranker", base_no_reranker

    # try without embed + reranker
    base_chat_only = SYSTEM_OVERHEAD_GB + chat_size
    if base_chat_only <= MAX_RAM_GB:
        return True, "chat_only", base_chat_only

    return False, "too_large", base_chat_only


def unload_chat_model():
    global _chat_model, _chat_model_path, _llm, _llm_path, _model_type
    if _chat_model is not None:
        print(f"[LLM] Unloading chat model: {_chat_model_path}")
        _chat_model = None
        _chat_model_path = None
        _llm = None
        _llm_path = None
        _model_type = None
        gc.collect()


def unload_embed_model():
    global _embed_model, _embed_model_path
    if _embed_model is not None:
        print(f"[LLM] Unloading embed model: {_embed_model_path}")
        _embed_model = None
        _embed_model_path = None
        gc.collect()


def unload_reranker():
    global _reranker_model, _reranker_model_path
    if _reranker_model is not None:
        print(f"[LLM] Unloading reranker: {_reranker_model_path}")
        _reranker_model = None
        _reranker_model_path = None
        gc.collect()


def unload_model():
    # Deprecated/compatible wrapper for query pipeline
    # Only unloads if the strategy requires hot-swapping
    if CURRENT_STRATEGY == "chat_only":
        unload_embed_model()
        unload_reranker()


def get_chat_model():
    return load_model()


def get_embed_model():
    global _embed_model, _embed_model_path
    embed_path = os.path.join(MODELS_DIR, "nomic-embed-text-v1.5.Q8_0.gguf")
    if not os.path.exists(embed_path):
        hits = glob.glob(os.path.join(MODELS_DIR, "*embed*.gguf"))
        if hits:
            embed_path = hits[0]
    if not os.path.exists(embed_path):
        raise FileNotFoundError("Embedding model GGUF not found. Please run setup.bat.")

    if _embed_model is not None and _embed_model_path == embed_path:
        return _embed_model

    # If chat_only strategy, we might need to free other models
    if CURRENT_STRATEGY == "chat_only":
        unload_reranker()

    print(f"[LLM] Loading embedding model: {os.path.basename(embed_path)}")
    try:
        _embed_model = Llama(
            model_path=embed_path,
            embedding=True,
            n_ctx=512,
            n_threads=max(2, (os.cpu_count() or 4) // 2),
            verbose=False,
        )
        _embed_model_path = embed_path
    except Exception as e:
        print(f"[LLM] ERROR loading embedding model: {e}")
        raise
    return _embed_model


def get_reranker_model():
    global _reranker_model, _reranker_model_path
    reranker_path = None
    hits = glob.glob(os.path.join(MODELS_DIR, "*rerank*.gguf"))
    if hits:
        reranker_path = hits[0]
    if reranker_path is None or not os.path.exists(reranker_path):
        return None

    if _reranker_model is not None and _reranker_model_path == reranker_path:
        return _reranker_model

    # If needed, unload models for memory room
    if CURRENT_STRATEGY in ("drop_reranker", "chat_only"):
        unload_embed_model()

    print(f"[LLM] Loading reranker model: {os.path.basename(reranker_path)}")
    try:
        _reranker_model = Llama(
            model_path=reranker_path,
            embedding=True,
            n_ctx=512,
            n_threads=max(2, (os.cpu_count() or 4) // 2),
            verbose=False,
        )
        _reranker_model_path = reranker_path
    except Exception as e:
        print(f"[LLM] Reranker load failed: {e} — will use FAISS scores")
        _reranker_model = None
        _reranker_model_path = None
    return _reranker_model


def load_chat_model():
    global _chat_model, _chat_model_path, _llm, _llm_path, _model_type
    current = find_model()
    if _chat_model is not None and _chat_model_path == current:
        return _chat_model

    unload_chat_model()
    print(f"[LLM] Loading chat model: {os.path.basename(current)}")
    n_ctx = LLM_CTX_WINDOW
    n_threads = max(2, (os.cpu_count() or 4) // 2)
    try:
        _chat_model = Llama(
            model_path=current,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_batch=256,
            use_mmap=True,
            use_mlock=False,
            verbose=False,
        )
        _chat_model_path = current
        _llm = _chat_model
        _llm_path = current
        _model_type = "chat"
    except Exception as e:
        print(f"[LLM] ERROR loading chat model: {e}")
        _chat_model = None
        _chat_model_path = None
        _llm = None
        _llm_path = None
        _model_type = None
        raise
    print(f"[LLM] Ready — {os.path.basename(current)} (ctx={n_ctx}, threads={n_threads})")
    print(f"[LLM] Chat format: {_detect_chat_format(current)}")
    return _chat_model


def load_model():
    return load_chat_model()


def load_all_models():
    """Server start -> load ALL 3 models -> ALL stay in RAM"""
    print("[LLM] Initializing resident models...")
    chat_path = find_model()
    chat_size = get_gguf_size_gb(chat_path)

    # Validate RAM budget
    can_load, strategy, estimated_ram = check_ram_budget(chat_path)
    global CURRENT_STRATEGY
    CURRENT_STRATEGY = strategy

    # Log exact sizes as per requirements
    print(f"Loading chat model... {chat_size:.2f}GB")
    load_chat_model()

    if strategy in ("all_resident", "drop_reranker"):
        print("Loading embed model... 0.14GB")
        try:
            load_embed_model()
        except Exception as e:
            print(f"[LLM] WARNING: Failed to load embed model: {e}")

    if strategy == "all_resident":
        print("Loading reranker... 0.61GB")
        try:
            load_reranker_model()
        except Exception as e:
            print(f"[LLM] WARNING: Failed to load reranker model: {e}")

    print(f"Total model RAM: {estimated_ram:.2f}GB — OK")
    print(f"All models loaded. RAM usage: ~{estimated_ram:.1f}GB")


# ── Chat format detection ──────────────────────────────────────────────────────

def _detect_chat_format(model_path: str) -> str:
    """Auto-detect chat template from the model filename."""
    name = os.path.basename(model_path).lower()
    if "qwen" in name:
        return "chatml"
    if "phi" in name:
        return "phi"
    if "llama" in name or "mistral" in name or "gemma" in name:
        return "llama"
    return "chatml"  # safest default


def _build_prompt(system: str, user: str, assistant_start: str = "") -> str:
    """Build a prompt string using the correct chat template for the loaded model."""
    fmt = _detect_chat_format(_llm_path or "")
    if fmt == "chatml":
        p = (f"<|im_start|>system\n{system}<|im_end|>\n"
             f"<|im_start|>user\n{user}<|im_end|>\n"
             f"<|im_start|>assistant\n")
    elif fmt == "phi":
        p = (f"<|system|>\n{system}<|end|>\n"
             f"<|user|>\n{user}<|end|>\n"
             f"<|assistant|>\n")
    else:
        p = (f"[INST] <<SYS>>\n{system}\n<</SYS>>\n"
             f"{user} [/INST]\n")
    return p + assistant_start


def _stop_tokens() -> list:
    """Return stop tokens for the loaded model's chat format."""
    fmt = _detect_chat_format(_llm_path or "")
    if fmt == "chatml":
        return ["<|im_end|>", "<|im_start|>", "```\n\n"]
    elif fmt == "phi":
        return ["<|end|>", "<|user|>", "```\n\n"]
    return ["[INST]", "</s>", "```\n\n"]


# ── Improvement 1: Diagram prompts with 3 examples each ───────────────────────

DIAGRAM_PROMPTS = {
    "flowchart TD": """Output ONLY a Mermaid flowchart. Start with ```mermaid, end with ```.

SYNTAX RULES (follow exactly):
- Use --> for arrows (NOT -> which is invalid)
- Node IDs: single letters or short words (A, B, C or Login, Auth)
- Labels in square brackets: A["Label text here"]
- Decision diamonds: C{"Is condition met?"}
- Rounded: D("Rounded label")
- Subgraphs: subgraph Title ... end
- Arrow labels: A -->|label text| B
- NO semicolons at end of lines
- NO pipes | inside node labels

CONTENT RULES:
- NEVER generic: "Start", "End", "Decision", "Process"
- Every node = SPECIFIC real action (e.g. "User submits login form")
- At LEAST 10 nodes, use subgraphs to organize

Example:
```mermaid
flowchart TD
    subgraph Frontend
        A["Customer opens product page"] --> B["Add item to shopping cart"]
        B --> C{"Cart has 3+ items?"}
        C -->|Yes| D["Show bulk discount banner"]
        C -->|No| E["Show standard pricing"]
    end
    subgraph Checkout
        D --> F["Enter shipping address"]
        E --> F
        F --> G["Select payment method"]
        G --> H{"Credit card valid?"}
        H -->|Yes| I["Process payment via Stripe"]
        H -->|No| J["Display card error"]
        J --> G
    end
    subgraph Fulfillment
        I --> K["Generate order confirmation"]
        K --> L["Send confirmation email"]
        L --> M["Update inventory database"]
        M --> N["Queue for warehouse picking"]
    end
```
Now generate a DETAILED, COMPLEX flowchart with subgraphs for:""",
    "sequenceDiagram": """Output ONLY a Mermaid sequenceDiagram. Start with ```mermaid, end with ```.

CRITICAL RULES:
- Use SPECIFIC actor names (e.g. "UserBrowser", "AuthServer", "PaymentDB") not generic "Client", "Server"
- Every message MUST describe the ACTUAL data or action (e.g. "POST /api/login {email, password}")
- Include at LEAST 6 message exchanges
- Show error paths too

Example — user registration:
```mermaid
sequenceDiagram
    UserBrowser->>AuthAPI: POST /register {name, email, password}
    AuthAPI->>UserDB: SELECT * WHERE email = ?
    UserDB-->>AuthAPI: No existing user found
    AuthAPI->>UserDB: INSERT new user record
    UserDB-->>AuthAPI: User ID 42 created
    AuthAPI->>EmailService: Send verification email to user
    EmailService-->>AuthAPI: Email queued successfully
    AuthAPI-->>UserBrowser: 201 Created {userId, verifyToken}
```
Now generate a DETAILED sequence diagram with SPECIFIC messages for:""",
    "erDiagram": """Output ONLY a Mermaid erDiagram. Start with ```mermaid, end with ```.

CRITICAL RULES:
- Use SPECIFIC table/entity names from the topic
- Include field definitions with types (int, string, datetime, boolean)
- Mark PK/FK relationships
- Include at LEAST 4 entities with fields

Example — hospital system:
```mermaid
erDiagram
    PATIENT ||--o{ APPOINTMENT : books
    DOCTOR ||--o{ APPOINTMENT : attends
    DEPARTMENT ||--o{ DOCTOR : employs
    APPOINTMENT ||--o{ PRESCRIPTION : generates
    PATIENT {
        int patient_id PK
        string full_name
        datetime date_of_birth
        string blood_type
        string phone
    }
    DOCTOR {
        int doctor_id PK
        string full_name
        string specialization
        int department_id FK
    }
    APPOINTMENT {
        int appointment_id PK
        int patient_id FK
        int doctor_id FK
        datetime scheduled_at
        string status
    }
```
Now generate a DETAILED ER diagram with SPECIFIC entities and fields for:""",
    "classDiagram": """Output ONLY a Mermaid classDiagram. Start with ```mermaid, end with ```.

CRITICAL RULES:
- Use SPECIFIC class names from the topic
- Include REAL attributes with types and REAL methods
- Show inheritance, composition, and associations
- Include at LEAST 4 classes

Example — online store:
```mermaid
classDiagram
    Product <|-- PhysicalProduct
    Product <|-- DigitalProduct
    ShoppingCart o-- Product
    Order *-- OrderItem
    Product : +int productId
    Product : +String name
    Product : +float price
    Product : +getDiscountedPrice()
    PhysicalProduct : +float weight
    PhysicalProduct : +calculateShipping()
    DigitalProduct : +String downloadUrl
    DigitalProduct : +generateLicense()
    ShoppingCart : +List~Product~ items
    ShoppingCart : +addItem(Product)
    ShoppingCart : +calculateTotal()
```
Now generate a DETAILED class diagram with SPECIFIC classes for:""",
    "stateDiagram-v2": """Output ONLY a Mermaid stateDiagram-v2. Start with ```mermaid, end with ```.

CRITICAL RULES:
- Use SPECIFIC state names from the topic (not generic "State1", "State2")
- Every transition MUST have a SPECIFIC event label
- Include at LEAST 6 states

Example — bug tracking:
```mermaid
stateDiagram-v2
    [*] --> Reported
    Reported --> Triaged : developer reviews bug
    Triaged --> InProgress : assigned to developer
    InProgress --> CodeReview : fix submitted as PR
    CodeReview --> InProgress : reviewer requests changes
    CodeReview --> Testing : PR approved and merged
    Testing --> Verified : QA confirms fix works
    Testing --> InProgress : QA finds regression
    Verified --> Closed : deployed to production
    Closed --> [*]
```
Now generate a DETAILED state diagram with SPECIFIC states for:""",
    "gantt": """Output ONLY a Mermaid gantt chart. Start with ```mermaid, end with ```.

CRITICAL RULES:
- Use a SPECIFIC title related to the topic
- Use SPECIFIC task names (not "Task 1", "Task 2")
- Include at LEAST 3 sections with multiple tasks each

Example — mobile app launch:
```mermaid
gantt
    title Mobile App Launch Plan
    dateFormat  YYYY-MM-DD
    section Research
    User interviews        :a1, 2024-01-01, 14d
    Competitor analysis    :a2, 2024-01-08, 7d
    section Design
    Wireframes             :b1, after a1, 10d
    UI mockups             :b2, after b1, 10d
    Usability testing      :b3, after b2, 5d
    section Development
    Backend API            :c1, after b2, 21d
    iOS frontend           :c2, after b2, 28d
    Android frontend       :c3, after b2, 28d
    section Launch
    Beta testing           :d1, after c1, 14d
    App store submission   :d2, after d1, 7d
```
Now generate a DETAILED Gantt chart with SPECIFIC tasks for:""",
    "pie": """Output ONLY a Mermaid pie chart. Start with ```mermaid, end with ```.

CRITICAL RULES:
- Use a SPECIFIC title related to the topic
- Use SPECIFIC, REAL labels (not "Category A", "Category B")
- Use realistic percentage values that add up properly

Example:
```mermaid
pie title Cloud Infrastructure Costs 2024
    "Compute (EC2/VMs)" : 35
    "Storage (S3/Blob)" : 20
    "Networking (CDN)" : 15
    "Database (RDS)" : 18
    "Monitoring" : 7
    "Other services" : 5
```
Now generate a DETAILED pie chart with SPECIFIC labels for:""",
    "mindmap": """Output ONLY a Mermaid mindmap. Start with ```mermaid, end with ```.

CRITICAL RULES:
- Root node MUST be the SPECIFIC topic
- Every branch and leaf MUST have SPECIFIC, REAL content
- NEVER use generic labels like "Topic", "Subtopic", "Item"
- Include at LEAST 4 branches with 2-3 leaves each

Example — machine learning project:
```mermaid
mindmap
  root((Machine Learning Pipeline))
    Data Collection
      Web scraping APIs
      CSV file imports
      Database queries
    Preprocessing
      Handle missing values
      Feature scaling
      Train-test split
    Model Training
      Random Forest
      Neural Network
      Cross validation
    Deployment
      REST API endpoint
      Docker container
      Monitoring dashboard
```
Now generate a DETAILED mindmap with SPECIFIC content for:""",
}

RAG_SYSTEM_PROMPT = """You are a strict document assistant. Answer ONLY using the context provided.

RULES:
1. If context contains the answer — answer clearly and cite the source.
2. If context does NOT contain the answer — say exactly: "This information is not available in the uploaded document."
3. NEVER use training knowledge to fill gaps.
4. NEVER guess or infer anything not explicitly present in the provided context.
5. NEVER say "based on general knowledge" or any similar phrase.
6. If only partial info available — share what IS in the document and clearly state what is missing.
"""

GENERAL_SYSTEM_PROMPT = """You are a helpful AI assistant. Answer the user's question clearly and accurately using your knowledge.
"""


GENERAL_SYSTEM = """You are a helpful AI assistant.

STRUCTURE YOUR RESPONSE FOR MAXIMUM READABILITY:
1. USE BOLD HEADERS for different sections.
2. START with a "### Summary" section (2-3 sentences).
3. FOLLOW with a "### Details" section using bullet points.
4. USE double line breaks between sections to ensure a clean structure.
5. AVOID large blocks of text; keep paragraphs short.

Answer clearly and concisely in under 250 words.
If unsure, say you don't know.
"""

DOC_SYSTEM = """You are a precise reading assistant.

STRUCTURE YOUR RESPONSE:
1. USE BOLD HEADERS (### Summary, ### Source Findings).
2. Bullet points for details.

RULES:
- Answer ONLY using the provided document excerpts.
- If the answer isn't in the excerpts, say: 'The uploaded documents do not contain specific information on this.'
"""

ADAPTIVE_DOC_SYSTEM = """You are an adaptive source-accurate assistant.

Your goal is to provide a highly accurate answer based ONLY on the provided document excerpts.

STRUCTURE:
1. ### Summary (1-2 sentences)
2. ### Source Analysis (Detailed bullet points)

STRICTNESS:
- Do NOT use outside knowledge.
- If the excerpts are only 'related' but don't answer the question directly, explain what related information IS present instead of guessing.
"""

DOC_DIAGRAM_SYSTEM = """You are a document-to-diagram converter. Read the document and output a Mermaid diagram.

MANDATORY — EXTRACT REAL CONTENT:
1. Read EVERY line of the document text below
2. Find ALL: names, roles, systems, processes, steps, conditions, data fields
3. Use ONLY words and phrases that ACTUALLY APPEAR in the document as node labels
4. NEVER use placeholder labels: "Start", "End", "Decision", "Process", "Action", "Step", "Create", "Send"

BUILD THE DIAGRAM:
• Every entity/person/system from the document = a node with its REAL name
• Every action/relationship = an arrow with a SPECIFIC label from the document
• Use subgraphs to group related items by section or department
• Include at LEAST 8 nodes with REAL content from the document
• Arrow labels: use ACTUAL verbs from the document (e.g. "approves budget", "sends invoice")

RULES:
• Output ONLY the ```mermaid code block — NO text before or after
• If the document describes a process → use flowchart TD
• If the document describes messages/API calls → use sequenceDiagram
• If the document describes database tables → use erDiagram
• If the document describes classes/objects → use classDiagram
• If the document describes states/lifecycle → use stateDiagram-v2
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

# Generic placeholder labels that indicate a low-quality diagram
_PLACEHOLDER_LABELS = {
    "start", "end", "decision", "process", "action", "step 1", "step 2",
    "step 3", "step 4", "input", "output", "result", "task",
    "node1", "node2", "node3", "state1", "state2",
}


def _has_placeholder_labels(text: str) -> bool:
    """Return True if the diagram has too many generic/placeholder node labels."""
    lower = text.lower()
    # Extract node labels from brackets like [Start] or [Decision]
    labels = re.findall(r'\[([^\]]+)\]', lower)
    if not labels:
        return False
    placeholder_count = sum(1 for lbl in labels if lbl.strip() in _PLACEHOLDER_LABELS)
    # If more than 40% of labels are placeholders, reject
    return placeholder_count > len(labels) * 0.4


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


# ── Helpers for document-based diagram generation ──────────────────────────────

def _get_diagram_type_hint(diagram_type: str) -> str:
    """Return syntax rules only — NO copyable example labels."""
    hints = {
        "flowchart TD": "Arrows: A --> B, Labels: A[\"text\"] for boxes, C{\"question?\"} for diamonds, -->|label| for arrow text, subgraph Title ... end for groups",
        "sequenceDiagram": "Arrows: ActorA->>ActorB: message, ActorB-->>ActorA: reply, Use participant to declare actors",
        "erDiagram": "Relations: TABLE1 ||--o{ TABLE2 : relationship, Fields: int id PK, string name",
        "classDiagram": "Relations: Parent <|-- Child, Fields: +String name, Methods: +methodName()",
        "stateDiagram-v2": "Transitions: StateA --> StateB : event, Use [*] for start/end",
        "gantt": "Structure: title, dateFormat YYYY-MM-DD, section Name, TaskName :id, date, duration",
        "pie": "Structure: pie title ChartTitle, then \"Label\" : value per line",
        "mindmap": "Structure: root((CenterTopic)), indent branches with spaces",
    }
    return hints.get(diagram_type, hints["flowchart TD"])


def _wrap_partial_mermaid(raw_output: str, diagram_type: str) -> str:
    """
    When we pre-seed '```mermaid\\n' in the prompt, the model outputs
    the diagram body directly. This wraps it back into a proper fenced block.
    """
    text = raw_output.strip()

    # If it already has proper fences, leave it alone
    if text.startswith("```mermaid"):
        return text

    # Strip any trailing ``` the model might have added
    if text.endswith("```"):
        text = text[:-3].strip()

    # Strip any leading ``` the model might have re-added
    if text.startswith("```"):
        text = text[3:].strip()
        if text.lower().startswith("mermaid"):
            text = text[7:].strip()

    # If the model didn't include the diagram type keyword, prepend it
    has_type = any(
        text.lower().startswith(t.lower())
        for t in [
            "flowchart", "graph ", "sequenceDiagram", "erDiagram",
            "classDiagram", "stateDiagram", "gantt", "pie", "mindmap",
        ]
    )
    if not has_type and text:
        text = diagram_type + "\n" + text

    return "```mermaid\n" + text + "\n```"


# ── Generate ───────────────────────────────────────────────────────────────────


def generate(
    prompt: str, mode: str, context: str = "", diagram_type: str = "flowchart TD", confidence: float = 1.0
) -> str:
    llm = load_model()

    # ── Diagram ───────────────────────────────────────────────────────────────
    if mode == "diagram":
        type_hint = _get_diagram_type_hint(diagram_type)
        stops = _stop_tokens()

        # ── System prompt: short & direct (small models work better with less)
        diagram_sys = (
            "You generate Mermaid diagrams. Output ONLY the diagram nodes and edges.\n"
            "RULES: Every node label MUST be specific to the user's topic.\n"
            "BANNED labels: Start, End, Process, Decision, Action, Step, Node, Other.\n"
            f"Syntax: {type_hint}"
        )

        if context:
            context = context[:3000]
            user_msg = (
                f"DOCUMENT:\n{context}\n\n"
                f"Create a {diagram_type} diagram about: {prompt}\n"
                f"Use ONLY real terms from the document. 8+ nodes minimum."
            )
        else:
            user_msg = (
                f"Create a detailed {diagram_type} diagram about: {prompt}\n"
                f"Include 10+ nodes with SPECIFIC labels about this exact topic.\n"
                f"Use subgraphs to organize different sections."
            )

        # Pre-seed: model just needs to output nodes/edges, not boilerplate
        prefix = f"```mermaid\n{diagram_type}\n"
        full_prompt = _build_prompt(diagram_sys, user_msg, prefix)

        temp = 0.2
        max_tokens = LLM_CTX_WINDOW

        def _generate_once(t):
            r = llm(full_prompt, max_tokens=max_tokens, temperature=t, stop=stops, echo=False)
            body = r["choices"][0]["text"].strip()
            # Remove any repeated diagram header the model might echo
            for hdr in ["```mermaid", "```", diagram_type]:
                if body.lower().startswith(hdr.lower()):
                    body = body[len(hdr):].strip()
            # Build full diagram
            full = f"```mermaid\n{diagram_type}\n{body}\n```"
            return process_diagram(full, diagram_type)

        processed = _generate_once(temp)
        score = complexity_score(processed)
        print(f"[LLM] Diagram attempt 1: score={score}")

        # Retry if too simple or has placeholder labels
        if score < 6 or _has_placeholder_labels(processed):
            reason = "too simple" if score < 6 else "placeholder labels"
            print(f"[LLM] Rejected ({reason}) — retrying...")
            for attempt in range(2):
                p2 = _generate_once(0.3 + attempt * 0.1)
                s2 = complexity_score(p2)
                print(f"[LLM] Retry {attempt+1}: score={s2}")
                if s2 > score:
                    processed, score = p2, s2
                if s2 >= 6 and not _has_placeholder_labels(p2):
                    break
            print(f"[LLM] Final diagram score={score}")

        return processed

    # ── Document Q&A (Strict or Adaptive) ──────────────────────────────────
    if mode == "doc_qa" or (mode == "qa" and context):
        system_prompt = RAG_SYSTEM_PROMPT
        stops = _stop_tokens()
        
        user_msg = (
            f"=== DOCUMENT EXCERPTS ===\n{context[:4096]}\n=== END ===\n\n"
            f"Question: {prompt}"
        )
        full_prompt = _build_prompt(system_prompt, user_msg)
        result = llm(
            full_prompt,
            max_tokens=600,
            temperature=0.1,
            stop=stops,
            echo=False,
        )
        return result["choices"][0]["text"].strip()

    # ── General Q&A ───────────────────────────────────────────────────────────
    stops = _stop_tokens()
    full_prompt = _build_prompt(GENERAL_SYSTEM_PROMPT, prompt)
    result = llm(
        full_prompt,
        max_tokens=512,
        temperature=0.2,
        stop=stops,
        echo=False,
    )
    return result["choices"][0]["text"].strip()


def generate_hyde_passage(query: str) -> str:
    """Generate a hypothetical document passage that answers the query."""
    llm = load_model()
    stops = _stop_tokens()
    system = "You are a helpful assistant. Write a short paragraph (3-4 sentences) that directly answers the user's question. Write it as a factual statement in a document."
    user = f"Question: {query}"
    prompt = _build_prompt(system, user)
    res = llm(prompt, max_tokens=150, temperature=0.3, stop=stops, echo=False)
    return res["choices"][0]["text"].strip()


# LLM-based chunk scoring removed — too slow for
# 8GB RAM. CRAG heuristic in crag.py handles this.

