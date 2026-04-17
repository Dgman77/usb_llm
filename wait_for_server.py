"""
wait_for_server.py — waits until FastAPI server is ready.
Uses only Python built-ins. No packages needed.
"""
import sys
import time
import urllib.request
import urllib.error

PORT    = 8787
TIMEOUT = 300  # 5 minutes — model loading can be slow on first run

print("  Waiting for server", end="", flush=True)

start = time.time()
dots  = 0

for i in range(TIMEOUT):
    try:
        urllib.request.urlopen(
            f"http://localhost:{PORT}/api/status",
            timeout=3
        )
        elapsed = int(time.time() - start)
        print(f"\n  Server ready! (took {elapsed}s)", flush=True)
        sys.exit(0)
    except Exception:
        time.sleep(1)
        dots += 1
        print(".", end="", flush=True)
        # every 30s print a reassurance message
        if dots % 30 == 0:
            elapsed = int(time.time() - start)
            print(f"\n  Still loading model... ({elapsed}s) — please wait", end="", flush=True)

print(f"\n  [TIMEOUT] Server did not respond in {TIMEOUT} seconds.", flush=True)
sys.exit(1)