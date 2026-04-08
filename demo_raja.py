"""
RajaBee Demo — Phase 1: Localhost Test
=======================================
Tests the hierarchical hive on a single machine using different ports.

Before running this demo:
1. Make sure Ollama is running with a small model (e.g., qwen2.5:1.5b)
2. Start Queen 1: python queen_http_wrapper.py --port 5000 --model qwen2.5:1.5b --workers 1
3. Start Queen 2: python queen_http_wrapper.py --port 5001 --model qwen2.5:1.5b --workers 1
4. Run this demo: python demo_raja.py

The RajaBee will connect to both Queens, split the task, delegate, and combine.
"""

import sys
import os

# Add HoneycombOfAI to path
HONEYCOMB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'HoneycombOfAI')
sys.path.insert(0, HONEYCOMB_PATH)

from raja_bee import RajaBee


def main():
    # Default Queen endpoints for localhost testing
    queen_endpoints = [
        "http://localhost:5000",
        "http://localhost:5001",
    ]

    # Allow custom endpoints via command line
    if len(sys.argv) > 1:
        queen_endpoints = sys.argv[1].split(',')

    # Create the RajaBee
    raja = RajaBee(
        model_name="llama3.2:3b",
        queen_endpoints=queen_endpoints
    )

    # Start and discover Queens
    if not raja.start():
        print("\nNo Queens available. Make sure to start Queen HTTP wrappers first!")
        print("Example:")
        print("  Terminal 1: python queen_http_wrapper.py --port 5000 --model qwen2.5:1.5b --workers 1")
        print("  Terminal 2: python queen_http_wrapper.py --port 5001 --model qwen2.5:1.5b --workers 1")
        print("  Terminal 3: python demo_raja.py")
        sys.exit(1)

    print("\n" + "="*60)
    print("  RajaBee is ready! Type a complex task and press Enter.")
    print("  Type 'quit' to exit.")
    print("="*60 + "\n")

    while True:
        try:
            task = input("\n👑👑 Royal Task: ").strip()
            if not task or task.lower() == 'quit':
                print("Raja Bee shutting down. Long live the King!")
                break

            royal_honey = raja.process_royal_nectar(task)
            print(f"\n{'='*60}")
            print("ROYAL HONEY:")
            print("="*60)
            print(royal_honey)
            print("="*60)

        except KeyboardInterrupt:
            print("\nRaja Bee shutting down.")
            break


if __name__ == '__main__':
    main()
