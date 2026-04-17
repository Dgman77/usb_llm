"""
chat.py - CLI Chat Interface for DiagramAI
Run directly: python chat.py
Or: .myenv\Scripts\python.exe chat.py
"""

import os
import sys

# USB-safe path detection
USB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(USB_ROOT, "backend")
sys.path.insert(0, BACKEND)

from llm import load_model, generate


def main():
    print("\n" + "=" * 50)
    print("  DiagramAI  --  CLI Chat")
    print("=" * 50)
    print("\nType 'exit' to quit, 'clear' to clear screen\n")

    print("Loading model...")
    load_model()
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
                print("\n" + "=" * 50)
                print("  DiagramAI  --  CLI Chat")
                print("=" * 50)
                print()
                continue

            response = generate(user_input, mode="qa")
            print(f"AI: {response}\n")

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}\n")


if __name__ == "__main__":
    main()
