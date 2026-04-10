"""
Phase 2 LAN Demo — RajaBee on Laptop, Queens on Desktop
=========================================================
THE FIRST CROSS-MACHINE HIERARCHICAL AI TEST!

Architecture:
    Laptop (RajaBee) ──LAN──> Desktop (10.0.0.5)
                                ├── Queen on port 5000 (1 worker, llama3.2:3b)
                                └── Queen on port 5001 (1 worker, llama3.2:3b)

Before running this demo:
    1. On Desktop, start Queens:
       cd GiantHoneyBee
       python queen_http_wrapper.py --port 5000 --model llama3.2:3b --workers 1
       python queen_http_wrapper.py --port 5001 --model llama3.2:3b --workers 1

    2. On Laptop, run this script:
       python demo_phase2_lan.py

    Optional: specify custom Desktop IP:
       python demo_phase2_lan.py --desktop-ip 192.168.1.100
"""

import sys
import os
import argparse
import time

# Add HoneycombOfAI to path
HONEYCOMB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'HoneycombOfAI')
sys.path.insert(0, HONEYCOMB_PATH)

from raja_bee import RajaBee


def main():
    parser = argparse.ArgumentParser(description="Phase 2 LAN Demo — RajaBee on Laptop, Queens on Desktop")
    parser.add_argument('--desktop-ip', type=str, default='10.0.0.5',
                        help='Desktop IP address (default: 10.0.0.5)')
    parser.add_argument('--queen-ports', type=str, default='5000,5001',
                        help='Comma-separated Queen ports on Desktop (default: 5000,5001)')
    parser.add_argument('--model', type=str, default='llama3.2:3b',
                        help='Ollama model for RajaBee on Laptop (default: llama3.2:3b)')
    args = parser.parse_args()

    ports = [p.strip() for p in args.queen_ports.split(',')]
    queen_endpoints = [f"http://{args.desktop_ip}:{port}" for port in ports]

    print("=" * 60)
    print("  PHASE 2: LAN TEST — CROSS-MACHINE HIERARCHY")
    print("=" * 60)
    print(f"  RajaBee: THIS machine (Laptop)")
    print(f"  RajaBee model: {args.model}")
    print(f"  Queens: Desktop at {args.desktop_ip}")
    print(f"  Queen endpoints: {', '.join(queen_endpoints)}")
    print("=" * 60)

    # Create the RajaBee on Laptop, pointing to Queens on Desktop
    raja = RajaBee(
        model_name=args.model,
        ollama_url="http://localhost:11434",  # Laptop's own Ollama
        queen_endpoints=queen_endpoints
    )

    if not raja.start():
        print("\nCannot reach Queens on Desktop!")
        print(f"Make sure Queens are running on {args.desktop_ip} ports {', '.join(ports)}")
        print("On Desktop, run:")
        for port in ports:
            print(f"  python queen_http_wrapper.py --port {port} --model llama3.2:3b --workers 1")
        sys.exit(1)

    print(f"\n  PHASE 2 LAN HIERARCHY IS READY!")
    print(f"  RajaBee (Laptop) → {len(queen_endpoints)} Queens (Desktop)")
    print(f"  Type a task and press Enter. Type 'quit' to exit.")
    print("=" * 60 + "\n")

    while True:
        try:
            task = input("\n👑 Royal Task (LAN): ").strip()
            if not task or task.lower() == 'quit':
                print("Raja Bee shutting down. Long live the King!")
                break

            start = time.time()
            royal_honey = raja.process_royal_nectar(task)
            elapsed = time.time() - start

            print(f"\n{'=' * 60}")
            print(f"ROYAL HONEY (Phase 2 LAN — {elapsed:.1f}s):")
            print("=" * 60)
            print(royal_honey)
            print("=" * 60)

        except KeyboardInterrupt:
            print("\nRaja Bee shutting down.")
            break


if __name__ == '__main__':
    main()
