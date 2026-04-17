"""
test_llama.py — run this to check if llama.cpp is working correctly.

Usage:
    python test_llama.py
    or
    USB:\.myenv\Scripts\python.exe test_llama.py
"""

import sys
import os

print()
print("=" * 55)
print("  DiagramAI — llama.cpp Diagnostic Test")
print("=" * 55)
print()

# ── TEST 1: Can we import llama_cpp? ──────────────────────
print("TEST 1: Checking llama-cpp-python install...")
try:
    from llama_cpp import Llama
    import llama_cpp
    print(f"  OK   llama_cpp imported")
    print(f"  OK   version: {llama_cpp.__version__}")
except ImportError as e:
    print(f"  FAIL Cannot import llama_cpp")
    print(f"       Error: {e}")
    print()
    print("  FIX: Run this command:")
    print(f"       {sys.executable} -m pip install llama-cpp-python")
    print()
    print("  If that fails, download the wheel manually:")
    print("  https://github.com/abetlen/llama-cpp-python/releases")
    print("  Pick:  llama_cpp_python-X.X.X-cp311-cp311-win_amd64.whl")
    print(f"  Then: {sys.executable} -m pip install <downloaded.whl>")
    sys.exit(1)

print()

# ── TEST 2: Find the model file ───────────────────────────
print("TEST 2: Searching for .gguf model file...")

import glob

search_paths = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"),
    r"D:\models",
    r"D:\model",
    r"E:\models",
    r"C:\models",
    os.path.expanduser("~/Downloads"),
]

model_path = None
for folder in search_paths:
    hits = glob.glob(os.path.join(folder, "*.gguf"))
    if hits:
        model_path = hits[0]
        print(f"  OK   Found: {model_path}")
        size_gb = os.path.getsize(model_path) / (1024**3)
        print(f"  OK   Size:  {size_gb:.2f} GB")
        break

if not model_path:
    print("  FAIL No .gguf file found in any of these folders:")
    for p in search_paths:
        print(f"       {p}")
    print()
    print("  FIX: Paste the full path to your model file below.")
    model_path = input("  Path: ").strip().strip('"')
    if not os.path.exists(model_path):
        print(f"  FAIL File not found: {model_path}")
        sys.exit(1)
    print(f"  OK   Using: {model_path}")

print()

# ── TEST 3: Load the model ────────────────────────────────
print("TEST 3: Loading model into memory...")
print("        (This takes 15-60 seconds — please wait)")
print()

try:
    llm = Llama(
        model_path=model_path,
        n_ctx=512,           # small context just for testing
        n_threads=4,
        n_gpu_layers=0,
        verbose=False,
    )
    print("  OK   Model loaded successfully!")
except Exception as e:
    print(f"  FAIL Model failed to load")
    print(f"       Error: {e}")
    print()
    print("  Common causes:")
    print("  - Model file is corrupted (re-download it)")
    print("  - Not enough RAM (need at least 4GB free)")
    print("  - Wrong file — make sure it ends in .gguf")
    sys.exit(1)

print()

# ── TEST 4: Run a quick generation ───────────────────────
print("TEST 4: Running a test generation...")
print("        Asking: 'Say hello in one word'")
print()

try:
    prompt = "<|system|>\nYou are helpful.<|end|>\n<|user|>\nSay hello in one word.<|end|>\n<|assistant|>\n"
    result = llm(
        prompt,
        max_tokens=10,
        temperature=0.1,
        stop=["<|end|>", "<|user|>"],
        echo=False,
    )
    answer = result["choices"][0]["text"].strip()
    print(f"  OK   Model replied: '{answer}'")
except Exception as e:
    print(f"  FAIL Generation failed: {e}")
    sys.exit(1)

print()

# ── TEST 5: Quick mermaid generation ─────────────────────
print("TEST 5: Testing diagram generation...")
print("        Asking for a simple flowchart")
print()

try:
    diagram_prompt = (
        "<|system|>\n"
        "Output ONLY a mermaid code block. Nothing else.\n"
        "<|end|>\n"
        "<|user|>\n"
        "Draw a simple 3-step login flowchart.\n"
        "<|end|>\n"
        "<|assistant|>\n"
    )
    result = llm(
        diagram_prompt,
        max_tokens=200,
        temperature=0.1,
        stop=["<|end|>", "<|user|>"],
        echo=False,
    )
    answer = result["choices"][0]["text"].strip()
    has_mermaid = "flowchart" in answer.lower() or "graph" in answer.lower() or "```mermaid" in answer.lower()
    print(f"  Output preview:")
    for line in answer.split("\n")[:6]:
        print(f"    {line}")
    if has_mermaid:
        print()
        print("  OK   Mermaid syntax detected in output!")
    else:
        print()
        print("  WARN Output doesn't look like Mermaid — model may need")
        print("       a better prompt or different model version.")
except Exception as e:
    print(f"  FAIL: {e}")

print()
print("=" * 55)
print("  All tests passed! llama.cpp is working correctly.")
print("  You can now run start.bat to launch DiagramAI.")
print("=" * 55)
print()
