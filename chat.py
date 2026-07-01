"""
chat.py - CLI Chat Interface for Flash AI with RAG
Run directly: python chat.py
Or via chat.bat from the USB root.
"""

import os
import sys

# USB-safe path detection:
# chat.py lives at the USB root (e.g. E:\usb_llm\chat.py)
# So __file__'s directory IS the USB root.
USB_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(USB_ROOT, "backend")

if not os.path.isdir(BACKEND):
    print(f"[ERROR] Backend folder not found: {BACKEND}")
    print("  Make sure chat.py is in the same folder as the 'backend' directory.")
    sys.exit(1)

sys.path.insert(0, BACKEND)

from llm import load_model, generate


def main():
    print("\n" + "=" * 50)
    print("  Flash AI with RAG   --  CLI Chat")
    print("=" * 50)
    print("\nType 'exit' to quit, 'clear' to clear screen\n")

    print("Loading model...")
    try:
        load_model()
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        print("  Drop a .gguf model into the 'models' folder and retry.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Model failed to load: {e}")
        sys.exit(1)
    print("Ready!\n")

    while True:
        try:
            user_input = input("You: ").strip()

            if not user_input:
                continue
            if user_input.lower() == "exit":
                print("\nGoodbye!")
                break
            if user_input.lower() == "clear":
                os.system("cls" if os.name == "nt" else "clear")
                print("=" * 50)
                print("  Flash AI with RAG   --  CLI Chat")
                print("=" * 50)
                print()
                continue

            response = generate(user_input, mode="qa")
            print(f"\nAI: {response}\n")

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"[Error] {e}\n")


if __name__ == "__main__":
    main()
