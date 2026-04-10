"""
GiantQueen HTTP Wrapper — Expose a RajaBee as an HTTP endpoint for N-level nesting
====================================================================================
Named after Apis dorsata (Giant Honey Bee). A GiantQueen is a mid/upper-level
coordinator that does NOT have Workers directly — she coordinates DwarfQueens
(or other GiantQueens for deeper hierarchies).

This wrapper turns a RajaBee into an HTTP service that looks IDENTICAL to a
DwarfQueen HTTP wrapper. A higher-level RajaBee can call it via the same /process
and /capabilities endpoints, without knowing there's an entire hierarchy inside.

This is what makes N-level hierarchies possible:
    Level 3 RajaBee → calls GiantQueen (RajaBee via this wrapper) → calls DwarfQueens → Workers

Endpoints:
    POST /process      — Send a task, get Royal Honey back
    GET  /capabilities — Report total workers across ALL nested DwarfQueens
    GET  /health       — Simple health check
"""

import sys
import os
import argparse
from flask import Flask, request, jsonify
import time

# Add HoneycombOfAI to path
HONEYCOMB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'HoneycombOfAI')
sys.path.insert(0, HONEYCOMB_PATH)

from raja_bee import RajaBee

app = Flask(__name__)

# Set in main()
raja = None
raja_stats = {"tasks_completed": 0, "total_time": 0.0}


@app.route('/process', methods=['POST'])
def process_task():
    """Accept a task, run it through the RajaBee hierarchy, return Royal Honey."""
    data = request.get_json()
    task = data.get('task', '')

    if not task:
        return jsonify({"error": "No task provided"}), 400

    start = time.time()
    result = raja.process_nectar(task)
    elapsed = time.time() - start

    raja_stats["tasks_completed"] += 1
    raja_stats["total_time"] += elapsed

    return jsonify({"result": result, "time": round(elapsed, 2)})


@app.route('/capabilities', methods=['GET'])
def capabilities():
    """Report total capabilities across ALL GiantQueens/DwarfQueens under this RajaBee."""
    total_workers = sum(
        c.get('total_workers', 1) for c in raja.giant_queen_capabilities.values()
    )
    avg_time = 0.0
    if raja_stats["tasks_completed"] > 0:
        avg_time = raja_stats["total_time"] / raja_stats["tasks_completed"]

    return jsonify({
        "total_workers": total_workers,
        "model": raja.model_name,
        "giant_queens": len(raja.giant_queen_capabilities),
        "tasks_completed": raja_stats["tasks_completed"],
        "avg_response_time": round(avg_time, 2),
        "type": "giant_queen"  # So higher levels know this is a GiantQueen (RajaBee inside), not a DwarfQueen
    })


@app.route('/health', methods=['GET'])
def health():
    """Simple health check."""
    return jsonify({
        "status": "alive",
        "type": "giant_queen",
        "giant_queens": len(raja.giant_queen_capabilities),
        "total_workers": sum(
            c.get('total_workers', 1) for c in raja.giant_queen_capabilities.values()
        )
    })


def main():
    global raja

    parser = argparse.ArgumentParser(description="GiantQueen HTTP Wrapper — expose a RajaBee as HTTP for N-level nesting")
    parser.add_argument('--port', type=int, default=6000, help='Port to listen on (default: 6000)')
    parser.add_argument('--model', type=str, default='llama3.2:3b', help='Ollama model for this RajaBee/GiantQueen')
    parser.add_argument('--dwarf-queens', type=str, required=True,
                        help='Comma-separated DwarfQueen/GiantQueen endpoints (e.g., http://localhost:5000,http://localhost:5001)')
    parser.add_argument('--ollama-url', type=str, default='http://localhost:11434', help='Ollama API URL')
    args = parser.parse_args()

    dwarf_queen_endpoints = [e.strip() for e in args.dwarf_queens.split(',')]

    # Create and start the RajaBee (which appears as a GiantQueen to higher levels)
    raja = RajaBee(
        model_name=args.model,
        ollama_url=args.ollama_url,
        giant_queen_endpoints=dwarf_queen_endpoints
    )

    if not raja.start():
        print("Failed to start GiantQueen. No DwarfQueens available!")
        sys.exit(1)

    total_workers = sum(c.get('total_workers', 1) for c in raja.giant_queen_capabilities.values())

    print(f"\n{'='*60}")
    print(f"  GiantQueen HTTP Wrapper running on port {args.port}")
    print(f"  Model: {args.model}")
    print(f"  DwarfQueens: {len(raja.giant_queen_capabilities)}")
    print(f"  Total workers (across all DwarfQueens): {total_workers}")
    print(f"  Endpoints:")
    print(f"    POST http://localhost:{args.port}/process")
    print(f"    GET  http://localhost:{args.port}/capabilities")
    print(f"    GET  http://localhost:{args.port}/health")
    print(f"{'='*60}\n")

    app.run(host='0.0.0.0', port=args.port, debug=False)


if __name__ == '__main__':
    main()
