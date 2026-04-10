"""
N-Level Hierarchy Demo — RajaBee on top of GiantQueens on top of DwarfQueens
=============================================================================
Tests 3-level deep hierarchy on a single machine.

Architecture:
    Level 3: Top RajaBee (this script)
      ├── Level 2: GiantQueen-A on port 6000 (RajaBee wrapped as HTTP)
      │     ├── DwarfQueen on port 5000 (1 worker)
      │     └── DwarfQueen on port 5001 (1 worker)
      └── Level 2: GiantQueen-B on port 6001 (RajaBee wrapped as HTTP)
            ├── DwarfQueen on port 5002 (1 worker)
            └── DwarfQueen on port 5003 (1 worker)

Before running this demo, start all services in order:
    1. python queen_http_wrapper.py --port 5000 --model qwen2.5:1.5b --workers 1
    2. python queen_http_wrapper.py --port 5001 --model qwen2.5:1.5b --workers 1
    3. python queen_http_wrapper.py --port 5002 --model qwen2.5:1.5b --workers 1
    4. python queen_http_wrapper.py --port 5003 --model qwen2.5:1.5b --workers 1
    5. python raja_http_wrapper.py --port 6000 --dwarf-queens http://localhost:5000,http://localhost:5001
    6. python raja_http_wrapper.py --port 6001 --dwarf-queens http://localhost:5002,http://localhost:5003
    7. python demo_n_level.py
"""

import sys
import os

# Add HoneycombOfAI to path
HONEYCOMB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'HoneycombOfAI')
sys.path.insert(0, HONEYCOMB_PATH)

from raja_bee import RajaBee


def main():
    # Level 2 GiantQueen endpoints (each wrapping 2 DwarfQueens via raja_http_wrapper)
    giant_queen_endpoints = [
        "http://localhost:6000",  # GiantQueen-A (DwarfQueens on 5000, 5001)
        "http://localhost:6001",  # GiantQueen-B (DwarfQueens on 5002, 5003)
    ]

    # Allow custom endpoints
    if len(sys.argv) > 1:
        giant_queen_endpoints = sys.argv[1].split(',')

    # Create the TOP-LEVEL RajaBee (Level 3)
    top_raja = RajaBee(
        model_name="llama3.2:3b",
        giant_queen_endpoints=giant_queen_endpoints  # These are GiantQueens (RajaBees wrapped as HTTP)
    )

    if not top_raja.start():
        print("\nNo Level-2 GiantQueens available. Start them first!")
        print("See demo_n_level.py docstring for setup instructions.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  N-LEVEL HIERARCHY TEST")
    print("  Level 3 RajaBee is ready!")
    print("  Underneath: 2 GiantQueens, each with 2 DwarfQueens, each with 1 Worker")
    print("  Total depth: 3 levels")
    print("  Total workers: 4")
    print("  Type a task and press Enter. Type 'quit' to exit.")
    print("=" * 60 + "\n")

    while True:
        try:
            task = input("\n👑👑👑 Supreme Royal Task: ").strip()
            if not task or task.lower() == 'quit':
                print("Top-level Raja Bee shutting down. The hierarchy crumbles!")
                break

            royal_honey = top_raja.process_royal_nectar(task)
            print(f"\n{'=' * 60}")
            print("SUPREME ROYAL HONEY (3-level hierarchy):")
            print("=" * 60)
            print(royal_honey)
            print("=" * 60)

        except KeyboardInterrupt:
            print("\nTop-level Raja Bee shutting down.")
            break


if __name__ == '__main__':
    main()
