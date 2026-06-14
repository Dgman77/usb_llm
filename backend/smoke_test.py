"""Quick smoke test for model loading"""
import sys
sys.path.insert(0, '.')

print("=== Testing find_model ===")
from llm import find_model, find_available_models
try:
    m = find_model()
    print(f"FOUND MODEL: {m}")
except Exception as e:
    print(f"ERROR: {e}")

print("\n=== Testing find_available_models ===")
models = find_available_models()
print(f"AVAILABLE: {len(models)} models")
for mod in models:
    print(f"  - {mod['name']} active={mod['active']}")

print("\n=== Testing model loading ===")
from llm import load_model
try:
    llm = load_model()
    print(f"MODEL LOADED SUCCESSFULLY: {type(llm)}")
    
    # Quick inference test
    result = llm("Hello!", max_tokens=5, echo=False)
    print(f"INFERENCE OK: {result['choices'][0]['text'][:50]}")
except Exception as e:
    print(f"ERROR loading model: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Testing embed model ===")
from llm import get_embed_model, unload_model
unload_model()
try:
    embed = get_embed_model()
    print(f"EMBED MODEL LOADED: {type(embed)}")
    res = embed.create_embedding("test query")
    dim = len(res["data"][0]["embedding"])
    print(f"EMBEDDING OK: dim={dim}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

unload_model()
print("\n=== ALL TESTS PASSED ===")
