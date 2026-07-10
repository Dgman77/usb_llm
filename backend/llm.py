"""
llm.py — AI model loader and diagram/QA generator.

Optimized for low-spec CPU environments:
  1. No Reranker: Removed to save ~636MB memory swapping/loading overhead.
  2. Persistent Embeddings: nomic-embed-text stays loaded in RAM.
  3. Simplified RAM budget.
"""

import os
import glob
import re
import gc
from llama_cpp import Llama
from diagram_engine import process_diagram, is_valid as is_valid_diagram, complexity_score

USB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(USB_ROOT, "models")


# ── Model finder ───────────────────────────────────────────────────────────────

def _sanitize_path(raw: str) -> str:
    """Clean up path strings that may have escaped backslashes."""
    cleaned = raw.strip().strip('"').strip("'").strip()
    cleaned = cleaned.replace('\\\\', '\\')
    cleaned = cleaned.replace('\\\\', '\\')  # second pass
    return cleaned


def _prefer_quantized(files: list) -> list:
    """Sort model files to prefer smaller quantized models (Q4 > Q5 > Q6 > Q8 > FP16)."""
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
        # Verify saved model path exists and is not an embedding/rerank model
        is_embed = any(term in os.path.basename(saved).lower() for term in ("embed", "rerank", "nomic"))
        if saved and os.path.exists(saved) and not is_embed:
            print(f"[LLM] Model  : {os.path.basename(saved)}")
            return saved
        else:
            # Stale or embedding path — remove and re-scan
            print(f"[LLM] Saved model path invalid or embedding model: {saved!r}")
            print(f"[LLM] Clearing model_path.txt and scanning models folder...")
            try:
                os.remove(path_file)
            except Exception:
                pass
    gguf_files = glob.glob(os.path.join(MODELS_DIR, "*.gguf"))
    chat_files = [f for f in gguf_files if "embed" not in os.path.basename(f).lower() and "rerank" not in os.path.basename(f).lower()]
    if chat_files:
        chat_files = _prefer_quantized(chat_files)
        chosen = chat_files[0]
        print(f"[LLM] Model  : {os.path.basename(chosen)}")
        # Save the freshly-discovered path for next time
        os.makedirs(MODELS_DIR, exist_ok=True)
        with open(path_file, "w", encoding="utf-8") as f:
            f.write(chosen)
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

    # Save new path to file
    path_file = os.path.join(MODELS_DIR, "model_path.txt")
    os.makedirs(MODELS_DIR, exist_ok=True)
    with open(path_file, "w", encoding="utf-8") as f:
        f.write(path)

    CURRENT_STRATEGY = strategy

    unload_chat_model()
    gc.collect()
    load_chat_model()
    try:
        get_embed_model()
    except Exception:
        pass
    print(f"Chat switched. Chat and embed models resident. RAM: {estimated_ram:.1f}GB")

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
LLM_CTX_WINDOW = 8192

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

# Default strategy
CURRENT_STRATEGY = "all_resident"

# Cached chat format — set once when model loads, avoids repeated filename parsing
_CACHED_CHAT_FORMAT: str = ""


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
                      reranker_resident=False):
    """
    Returns (can_load, strategy, estimated_ram)
    """
    chat_size = get_gguf_size_gb(chat_model_path)
    base = SYSTEM_OVERHEAD_GB + chat_size + EMBED_SIZE_GB
    return True, "all_resident", base


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
    # Keep embedding model resident as a core RAG component
    pass


def unload_reranker():
    pass


def unload_model():
    pass


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
    # Deprecated for low spec optimizations
    return None


def load_chat_model():
    global _chat_model, _chat_model_path, _llm, _llm_path, _model_type, _CACHED_CHAT_FORMAT
    current = find_model()
    if _chat_model is not None and _chat_model_path == current:
        return _chat_model

    unload_chat_model()
    print(f"[LLM] Loading chat model: {os.path.basename(current)}")
    n_ctx = LLM_CTX_WINDOW
    # Use all CPUs except one (for OS), minimum 4
    n_threads = max(4, (os.cpu_count() or 4) - 1)
    try:
        _chat_model = Llama(
            model_path=current,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_batch=512,        # Increased from 256 for better CPU throughput
            use_mmap=True,
            use_mlock=False,
            verbose=False,
        )
        _chat_model_path = current
        _llm = _chat_model
        _llm_path = current
        _model_type = "chat"
        # Cache format so _build_prompt never re-parses the filename
        _CACHED_CHAT_FORMAT = _detect_chat_format(current)
    except Exception as e:
        print(f"[LLM] ERROR loading chat model: {e}")
        _chat_model = None
        _chat_model_path = None
        _llm = None
        _llm_path = None
        _model_type = None
        _CACHED_CHAT_FORMAT = ""
        raise
    print(f"[LLM] Ready — {os.path.basename(current)} (ctx={n_ctx}, threads={n_threads}, batch=512)")
    print(f"[LLM] Chat format: {_CACHED_CHAT_FORMAT}")
    return _chat_model


def load_model():
    return load_chat_model()


def load_all_models():
    """Server start -> load chat + embed models -> stay in RAM"""
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

    print("Loading embed model... 0.14GB")
    try:
        get_embed_model()
    except Exception as e:
        print(f"[LLM] WARNING: Failed to load embed model: {e}")

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
    # Use cached format to avoid repeated filename parsing
    fmt = _CACHED_CHAT_FORMAT or _detect_chat_format(_llm_path or "")
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
    fmt = _CACHED_CHAT_FORMAT or _detect_chat_format(_llm_path or "")
    if fmt == "chatml":
        return ["<|im_end|>", "<|im_start|>"]
    elif fmt == "phi":
        return ["<|end|>", "<|user|>"]
    return ["[INST]", "</s>"]


# ── Improvement 1: Diagram prompts with DOT examples ──────────────────────────

DIAGRAM_PROMPTS = {
    "dot": """Output ONLY valid Graphviz DOT code. Start with `digraph G {`. Use `rankdir`, `node [shape=box]`, and `edge` attributes. No markdown fences. No explanation text. No commentary.

    SYNTAX RULES:
    - Start with: digraph G {
    - Node IDs: short alphanumeric (A, B, Login, Auth)
    - Labels: A [label="Label text"];
    - Edges: A -> B;
    - Edge labels: A -> B [label="description"];
    - Subgraphs: subgraph cluster_Name { label="Title"; ... }
    - End with: }

    STYLING:
    - node [shape=box, style="rounded,filled", fillcolor="#faf6ee", fontname="Arial", fontsize=12];
    - edge [fontname="Arial", fontsize=11, fontcolor="#000000"];
    - All node labels must be SPECIFIC real actions from the topic

    CONTENT RULES:
    - NEVER generic: "Start", "End", "Decision", "Process"
    - Every node = SPECIFIC real action
    - At LEAST 10 nodes, use subgraphs to organize
    - Edge labels must describe actual data or actions

    Example:
    digraph G {
        rankdir=TB;
        node [shape=box, style="rounded,filled", fillcolor="#faf6ee", fontname="Arial", fontsize=12];
        edge [fontname="Arial", fontsize=11, fontcolor="#000000"];
        subgraph cluster_Frontend {
            label="Frontend";
            A [label="Customer opens product page"];
            B [label="Add item to shopping cart"];
            C [label="Cart has 3+ items?" shape=diamond];
            D [label="Show bulk discount"];
            E [label="Standard pricing"];
            A -> B;
            B -> C;
            C -> D [label="Yes"];
            C -> E [label="No"];
        }
        subgraph cluster_Checkout {
            label="Checkout";
            F [label="Enter shipping address"];
            G [label="Select payment method"];
            H [label="Credit card valid?" shape=diamond];
            I [label="Process payment via Stripe"];
            J [label="Display card error"];
            D -> F;
            E -> F;
            F -> G;
            G -> H;
            H -> I [label="Yes"];
            H -> J [label="No"];
            J -> G;
        }
        subgraph cluster_Fulfillment {
            label="Fulfillment";
            K [label="Generate order confirmation"];
            L [label="Send confirmation email"];
            M [label="Update inventory database"];
            I -> K;
            K -> L;
            L -> M;
        }
    }
    Now generate a DETAILED, COMPLEX DOT digraph with subgraphs for:""",
    "dot_sequence": """Output ONLY valid Graphviz DOT code. Start with `digraph G {`. No markdown fences. No explanation.

Use rankdir=LR for left-to-right sequence flow.

CRITICAL RULES:
- Use SPECIFIC actor/system names
- Every edge label MUST describe the ACTUAL data or action
- Include at LEAST 6 message exchanges
- Use invisible edges for ordering

Example — user registration:
digraph G {
    rankdir=LR;
    node [shape=box, style="rounded,filled", fillcolor="#faf6ee"];
    UserBrowser [label="User Browser"];
    AuthAPI [label="Auth API"];
    UserDB [label="User DB"];
    EmailSvc [label="Email Service"];
    UserBrowser -> AuthAPI [label="POST /register"];
    AuthAPI -> UserDB [label="SELECT WHERE email=?"];
    UserDB -> AuthAPI [label="No existing user" style=dashed];
    AuthAPI -> UserDB [label="INSERT new user"];
    UserDB -> AuthAPI [label="User ID 42 created" style=dashed];
    AuthAPI -> EmailSvc [label="Send verification email"];
    EmailSvc -> AuthAPI [label="Email queued" style=dashed];
    AuthAPI -> UserBrowser [label="201 Created" style=dashed];
}
Now generate a DETAILED sequence-style DOT diagram with SPECIFIC messages for:""",
    "fdp_er": """Output ONLY valid Graphviz DOT code for an entity-relationship diagram. Start with `graph ER {`. No markdown fences. No explanation.

CRITICAL RULES:
- Use SPECIFIC table/entity names from the topic
- Show fields inside HTML-like labels or record shapes
- Include at LEAST 4 entities
- Use -- for undirected edges with relationship labels

Example — hospital system:
graph ER {
    layout=fdp;
    node [shape=record, style=filled, fillcolor="#faf6ee"];
    Patient [label="{Patient|patient_id : int PK\\lfull_name : string\\ldate_of_birth : date\\lblood_type : string\\l}"];
    Doctor [label="{Doctor|doctor_id : int PK\\lfull_name : string\\lspecialization : string\\ldepartment_id : int FK\\l}"];
    Appointment [label="{Appointment|appt_id : int PK\\lpatient_id : int FK\\ldoctor_id : int FK\\lscheduled_at : datetime\\lstatus : string\\l}"];
    Department [label="{Department|dept_id : int PK\\lname : string\\lfloor : int\\l}"];
    Patient -- Appointment [label="books"];
    Doctor -- Appointment [label="attends"];
    Department -- Doctor [label="employs"];
}
Now generate a DETAILED ER DOT diagram with SPECIFIC entities and fields for:""",
    "fdp_class": """Output ONLY valid Graphviz DOT code for a class diagram. Start with `digraph G {`. No markdown fences. No explanation.

CRITICAL RULES:
- Use SPECIFIC class names from the topic
- Include REAL attributes and methods in record labels
- Show inheritance with edge [arrowhead=empty]
- Include at LEAST 4 classes

Example — online store:
digraph G {
    rankdir=BT;
    node [shape=record, style=filled, fillcolor="#faf6ee"];
    Product [label="{Product|+productId : int\\l+name : String\\l+price : float\\l|+getDiscountedPrice()\\l}"];
    PhysicalProduct [label="{PhysicalProduct|+weight : float\\l|+calculateShipping()\\l}"];
    DigitalProduct [label="{DigitalProduct|+downloadUrl : String\\l|+generateLicense()\\l}"];
    ShoppingCart [label="{ShoppingCart|+items : List\\l|+addItem()\\l+calculateTotal()\\l}"];
    PhysicalProduct -> Product [arrowhead=empty];
    DigitalProduct -> Product [arrowhead=empty];
    ShoppingCart -> Product [arrowhead=diamond, label="contains"];
}
Now generate a DETAILED class DOT diagram with SPECIFIC classes for:""",
    "dot_state": """Output ONLY valid Graphviz DOT code for a state diagram. Start with `digraph G {`. No markdown fences. No explanation.

CRITICAL RULES:
- Use SPECIFIC state names from the topic
- Every transition MUST have a SPECIFIC event label
- Include at LEAST 6 states
- Use point shape for start/end nodes

Example — bug tracking:
digraph G {
    rankdir=LR;
    node [shape=box, style="rounded,filled", fillcolor="#faf6ee"];
    start [shape=point, width=0.2];
    end_state [shape=doublecircle, width=0.3, label=""];
    Reported [label="Reported"];
    Triaged [label="Triaged"];
    InProgress [label="In Progress"];
    CodeReview [label="Code Review"];
    Testing [label="Testing"];
    Verified [label="Verified"];
    Closed [label="Closed"];
    start -> Reported;
    Reported -> Triaged [label="developer reviews"];
    Triaged -> InProgress [label="assigned"];
    InProgress -> CodeReview [label="PR submitted"];
    CodeReview -> InProgress [label="changes requested"];
    CodeReview -> Testing [label="PR merged"];
    Testing -> Verified [label="QA passed"];
    Testing -> InProgress [label="regression found"];
    Verified -> Closed [label="deployed"];
    Closed -> end_state;
}
Now generate a DETAILED state DOT diagram with SPECIFIC states for:""",
    "dot_gantt": """Output ONLY valid Graphviz DOT code representing a timeline/schedule. Start with `digraph G {`. No markdown fences. No explanation.

CRITICAL RULES:
- Use rankdir=LR for timeline flow
- Use SPECIFIC task tasks from the topic
- Group into subgraph clusters by phase
- Include at LEAST 8 tasks across 3+ phases

Example — mobile app launch:
digraph G {
    rankdir=LR;
    node [shape=box, style="filled,rounded", fillcolor="#faf6ee"];
    subgraph cluster_Research {
        label="Research";
        A [label="User interviews\\n14 days"];
        B [label="Competitor analysis\\n7 days"];
        A -> B;
    }
    subgraph cluster_Design {
        label="Design";
        C [label="Wireframes\\n10 days"];
        D [label="UI mockups\\n10 days"];
        E [label="Usability testing\\n5 days"];
        C -> D -> E;
    }
    subgraph cluster_Dev {
        label="Development";
        F [label="Backend API\\n21 days"];
        G [label="iOS frontend\\n28 days"];
        H [label="Android frontend\\n28 days"];
    }
    B -> C;
    E -> F;
    E -> G;
    E -> H;
}
Now generate a DETAILED timeline/Gantt DOT diagram with SPECIFIC tasks for:""",
    "dot_pie": """Output ONLY valid Graphviz DOT code representing a data distribution. Start with `digraph G {`. No markdown fences. No explanation.

Since Graphviz doesn't natively support pie charts, use a radial layout with sized nodes.

CRITICAL RULES:
- Use SPECIFIC, REAL labels
- Show percentages in labels
- Use different fillcolors for each segment

Example:
digraph G {
    rankdir=TB;
    label="Cloud Infrastructure Costs 2024";
    labelloc=t;
    fontsize=16;
    node [shape=box, style="filled,rounded"];
    A [label="Compute (EC2/VMs)\\n35%" fillcolor="#f59e0b"];
    B [label="Storage (S3/Blob)\\n20%" fillcolor="#14b8a6"];
    C [label="Networking (CDN)\\n15%" fillcolor="#6366f1"];
    D [label="Database (RDS)\\n18%" fillcolor="#f43f5e"];
    E [label="Monitoring\\n7%" fillcolor="#10b981"];
    F [label="Other services\\n5%" fillcolor="#8b5cf6"];
    Center [label="Total Budget" shape=ellipse, style="filled", fillcolor="#fdf8f0"];
    Center -> A;
    Center -> B;
    Center -> C;
    Center -> D;
    Center -> E;
    Center -> F;
}
Now generate a DETAILED distribution DOT diagram with SPECIFIC labels for:""",
    "twopi": """Output ONLY valid Graphviz DOT code for a mind map. Start with `digraph G {`. Use layout=twopi. No markdown fences. No explanation.

CRITICAL RULES:
- Root node MUST be the SPECIFIC topic (use ellipse shape)
- Every branch and leaf MUST have SPECIFIC, REAL content
- Central node must represent the query topic
- Include at LEAST 4 branches with 2-3 leaves each

Example — machine learning:
digraph G {
    layout=twopi;
    root=center;
    node [shape=box, style="filled,rounded", fillcolor="#faf6ee"];
    center [label="ML Pipeline" shape=ellipse, fillcolor="#fef3e2", fontsize=14];
    dc [label="Data Collection"];
    dc1 [label="Web scraping APIs"];
    dc2 [label="CSV file imports"];
    dc3 [label="Database queries"];
    pp [label="Preprocessing"];
    pp1 [label="Handle missing values"];
    pp2 [label="Feature scaling"];
    pp3 [label="Train-test split"];
    mt [label="Model Training"];
    mt1 [label="Random Forest"];
    mt2 [label="Neural Network"];
    mt3 [label="Cross validation"];
    dp [label="Deployment"];
    dp1 [label="REST API endpoint"];
    dp2 [label="Docker container"];
    dp3 [label="Monitoring dashboard"];
    center -> dc;
    center -> pp;
    center -> mt;
    center -> dp;
    dc -> dc1; dc -> dc2; dc -> dc3;
    pp -> pp1; pp -> pp2; pp -> pp3;
    mt -> mt1; mt -> mt2; mt -> mt3;
    dp -> dp1; dp -> dp2; dp -> dp3;
}
Now generate a DETAILED mind map DOT diagram with SPECIFIC content for:""",
}

RAG_SYSTEM_PROMPT = """You are a strict document assistant. Answer ONLY using the context provided.
Your task is to list the direct, related factual statements from the context that answer the question. Format the statements clearly as a bulleted list (point by point). Do not generate your own answer.

RULES:
1. List only the direct, related facts from the context. Do not explain, summarize, or extrapolate.
2. If the context does not contain any direct related information to answer the question, output exactly: "This information is not available in the uploaded document."
3. Do not make assumptions or use outside knowledge.
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

DOC_DIAGRAM_SYSTEM = """You are a document-to-diagram converter. Read the document and output valid Graphviz DOT code.

Output only valid Graphviz DOT code. Start with `digraph G {`. Use `rankdir`, `node [shape=box]`, and `edge` attributes. No markdown fences. No explanation text. No commentary.

MANDATORY — EXTRACT REAL CONTENT:
1. Read EVERY line of the document text below
2. Find ALL: names, roles, systems, processes, steps, conditions, data fields
3. Use ONLY words and phrases that ACTUALLY APPEAR in the document as node labels
4. NEVER use placeholder labels: "Start", "End", "Decision", "Process", "Action", "Step", "Create", "Send"

BUILD THE DIAGRAM:
• Every entity/person/system from the document = a node with its REAL name
• Every action/relationship = an edge with a SPECIFIC label from the document
• Use subgraph cluster_ groups to organize related items by section
• Include at LEAST 8 nodes with REAL content from the document
• Edge labels: use ACTUAL verbs from the document (e.g. label="approves budget")

RULES:
• Output ONLY valid DOT code — NO text before or after
• Start with digraph G { and end with }
• Use node [shape=box, style=\"rounded,filled\", fillcolor=\"#faf6ee\"] for styling
• Use A -> B [label=\"action\"] for labeled edges
"""


# ── Improvement 2: Output validator ───────────────────────────────────────────

# Generic placeholder labels that indicate a low-quality diagram
_PLACEHOLDER_LABELS = {
    "start", "end", "decision", "process", "action", "step 1", "step 2",
    "step 3", "step 4", "input", "output", "result", "task",
    "node1", "node2", "node3", "state1", "state2",
}


def _has_placeholder_labels(text: str) -> bool:
    """Return True if the diagram has too many generic/placeholder node labels."""
    lower = text.lower()
    # Extract node labels from label="..." attributes in DOT
    labels = re.findall(r'label\s*=\s*"([^"]+)"', lower)
    if not labels:
        return False
    placeholder_count = sum(1 for lbl in labels if lbl.strip() in _PLACEHOLDER_LABELS)
    # If more than 40% of labels are placeholders, reject
    return placeholder_count > len(labels) * 0.4


def _is_valid_dot(text: str) -> bool:
    """Check if text contains valid Graphviz DOT code."""
    lower = text.lower()
    has_graph = "digraph" in lower or re.search(r'\bgraph\b', lower) is not None
    has_edge = "->" in text or "--" in text
    return has_graph and has_edge


def _extract_or_fix(text: str) -> str:
    """
    Try to extract DOT code from LLM output.
    If model used fences, strip them. If no digraph wrapper, add one.
    """
    # Has ```dot or ```graphviz fence
    m = re.search(r"```(?:dot|graphviz)\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Has generic ``` fence with DOT inside
    m = re.search(r"```\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        inner = m.group(1).strip()
        if "digraph" in inner.lower() or re.search(r'\bgraph\b', inner, re.I):
            return inner

    # No fence but has digraph/graph keyword — extract from there
    stripped = text.strip()
    for line_no, line in enumerate(stripped.splitlines()):
        ll = line.strip().lower()
        if ll.startswith("digraph") or re.match(r'^graph\b', ll):
            return "\n".join(stripped.splitlines()[line_no:]).strip()

    return stripped  # return as-is


# ── Helpers for document-based diagram generation ──────────────────────────────

def _get_diagram_type_hint(layout_engine: str) -> str:
    """Return DOT syntax rules for the given layout engine."""
    hints = {
        "dot": "Start with digraph G {. Nodes: A [label=\"text\"]; Edges: A -> B [label=\"action\"]; Subgraphs: subgraph cluster_Name { label=\"Title\"; ... }",
        "fdp": "Start with graph ER {. Nodes: A [label=\"text\" shape=record]; Edges: A -- B [label=\"rel\"]; Use layout=fdp;",
        "twopi": "Start with digraph G {. Use layout=twopi; root=center; Center node with shape=ellipse. Branch nodes: center -> branch; Leaf nodes: branch -> leaf;",
    }
    return hints.get(layout_engine, hints["dot"])


def _wrap_partial_dot(raw_output: str, layout_engine: str) -> str:
    """
    When we pre-seed 'digraph G {' in the prompt, the model outputs
    the body directly. This wraps it back into a proper DOT string.
    """
    text = raw_output.strip()

    # If it already has a digraph/graph wrapper, leave it alone
    if re.match(r'^(strict\s+)?(di)?graph\b', text, re.I):
        return text

    # Strip any fences the model might have added
    if text.startswith("```"):
        # Remove opening fence
        text = re.sub(r'^```(?:dot|graphviz)?\s*\n?', '', text)
    if text.endswith("```"):
        text = text[:-3].strip()

    # If the model included digraph G { after stripping, return as-is
    if re.match(r'^(strict\s+)?(di)?graph\b', text, re.I):
        return text

    # Wrap in digraph
    if layout_engine == "fdp":
        return f"graph G {{\n    layout=fdp;\n{text}\n}}"
    else:
        return f"digraph G {{\n{text}\n}}"


# ── Generate ───────────────────────────────────────────────────────────────────


def generate(
    prompt: str, mode: str, context: str = "", diagram_type: str = "dot", confidence: float = 1.0
) -> str:
    llm = load_model()

    # ── Diagram ───────────────────────────────────────────────────────────────
    if mode == "diagram":
        layout_engine = diagram_type  # now a DOT layout engine string
        type_hint = _get_diagram_type_hint(layout_engine)
        stops = _stop_tokens()

        # ── System prompt: short & direct (small models work better with less)
        diagram_sys = (
    "Output only valid Graphviz DOT code. Start with `digraph G {`. "
    "Always include `rankdir`, `node [shape=box]`, and `edge` attributes. "
    "Use `fontname=\"Arial\"` and `fontsize=12` for nodes, `fontsize=11` for edges. "
    "Do not use markdown fences, explanation text, or commentary. "
    "RULES: Every node label MUST be specific to the user's topic. "
    "BANNED labels: Start, End, Process, Decision, Action, Step, Node, Other. "
    "Syntax must strictly follow Graphviz DOT standards. "
    "Do not hallucinate or invent labels, attributes, or structures. "
    "If the user's prompt does not provide enough detail, ask for clarification before generating code. "
    "Never repeat the same code or explanation unnecessarily. "
    "Always rely on the user's prompt as the single source of truth. "
    "Do not ever hallucinate your answer — rely only on the user's prompt. "
    f"Syntax: {type_hint}"
)


        if context:
            context = context[:3000]
            user_msg = (
                f"DOCUMENT:\n{context}\n\n"
                f"Create a DOT digraph about: {prompt}\n"
                f"Use ONLY real terms from the document. 8+ nodes minimum."
            )
        else:
            # Look up diagram-type-specific prompt
            prompt_key = layout_engine
            # Map internal keys to DIAGRAM_PROMPTS keys
            if prompt_key not in DIAGRAM_PROMPTS:
                prompt_key = "dot"  # default fallback
            user_msg = DIAGRAM_PROMPTS.get(prompt_key, DIAGRAM_PROMPTS["dot"]) + f" {prompt}"

        # Pre-seed: model outputs DOT body directly
        prefix = "digraph G {\n"
        full_prompt = _build_prompt(diagram_sys, user_msg, prefix)

        # Diagram-specific token budget:
        # max_tokens must fit WITHIN n_ctx minus the prompt length.
        # 1024 new tokens is plenty for a rich DOT diagram.
        max_new_tokens = min(1024, LLM_CTX_WINDOW - 512)
        temp = 0.2

        def _generate_once(t):
            r = llm(full_prompt, max_tokens=max_new_tokens, temperature=t, stop=stops, echo=False)
            body = r["choices"][0]["text"].strip()
            # Remove any repeated digraph header the model might echo
            if body.lower().startswith("digraph"):
                pass  # keep it, process_diagram will handle
            # Build full DOT
            full = f"digraph G {{\n{body}"
            # Ensure closing brace
            if full.count("{") > full.count("}"):
                full += "\n}" * (full.count("{") - full.count("}"))
            return process_diagram(full, layout_engine)

        processed = _generate_once(temp)
        score = complexity_score(processed)
        print(f"[LLM] Diagram attempt 1: score={score}")

        # Retry only if too simple or plagued by placeholder labels
        if score < 6 or _has_placeholder_labels(processed):
            reason = "too simple" if score < 6 else "placeholder labels"
            print(f"[LLM] Rejected ({reason}) — retrying...")
            for attempt in range(2):
                p2 = _generate_once(0.3 + attempt * 0.1)
                s2 = complexity_score(p2)
                print(f"[LLM] Retry {attempt+1}: score={s2}")
                if s2 > score:
                    processed, score = p2, s2
                # Break early once we have a good diagram
                if s2 >= 6 and not _has_placeholder_labels(p2):
                    print(f"[LLM] Early-exit retry after attempt {attempt+1}")
                    break
            print(f"[LLM] Final diagram score={score}")

        return processed

    # ── Document Q&A (Strict or Adaptive) ──────────────────────────────────
    if mode == "doc_qa" or (mode == "qa" and context):
        system_prompt = RAG_SYSTEM_PROMPT
        stops = _stop_tokens()
        
        user_msg = (
            f"<context>\n{context[:4096]}\n</context>\n\n"
            f"Question: {prompt}"
        )
        full_prompt = _build_prompt(system_prompt, user_msg)
        result = llm(
            full_prompt,
            max_tokens=600,
            temperature=0.1,
            repeat_penalty=1.1, # Prevent repetition loops on low temperatures
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
        repeat_penalty=1.1, # Prevent repetition loops
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
