"""
Raja HTTP Wrapper — Expose a RajaBee as an HTTP endpoint for N-level nesting
=============================================================================
This wrapper turns a RajaBee into an HTTP service that looks IDENTICAL to a
Queen HTTP wrapper. A higher-level RajaBee can call it via the same /process
and /capabilities endpoints, without knowing there's an entire hierarchy inside.

This is what makes N-level hierarchies possible:
    Level 3 RajaBee → calls Level 2 RajaBee (via this wrapper) → calls Queens → Workers

Endpoints:
    POST /process      — Send a task, get Royal Honey back
    GET  /capabilities — Report total workers across ALL nested Queens
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
    """Report total capabilities across ALL Queens under this RajaBee."""
    total_workers = sum(
        c.get('total_workers', 1) for c in raja.queen_capabilities.values()
    )
    avg_time = 0.0
    if raja_stats["tasks_completed"] > 0:
        avg_time = raja_stats["total_time"] / raja_stats["tasks_completed"]

    return jsonify({
        "total_workers": total_workers,
        "model": raja.model_name,
        "queens": len(raja.queen_capabilities),
        "tasks_completed": raja_stats["tasks_completed"],
        "avg_response_time": round(avg_time, 2),
        "type": "raja"  # So higher levels know this is a RajaBee, not a single Queen
    })


@app.route('/health', methods=['GET'])
def health():
    """Simple health check."""
    return jsonify({
        "status": "alive",
        "type": "raja",
        "queens": len(raja.queen_capabilities),
        "total_workers": sum(
            c.get('total_workers', 1) for c in raja.queen_capabilities.values()
        )
    })


def main():
    global raja

    parser = argparse.ArgumentParser(description="Raja HTTP Wrapper — expose a RajaBee as HTTP for N-level nesting")
    parser.add_argument('--port', type=int, default=6000, help='Port to listen on (default: 6000)')
    parser.add_argument('--model', type=str, default='llama3.2:3b', help='Ollama model for this RajaBee')
    parser.add_argument('--queens', type=str, required=True,
                        help='Comma-separated Queen/Raja endpoints (e.g., http://localhost:5000,http://localhost:5001)')
    parser.add_argument('--ollama-url', type=str, default='http://localhost:11434', help='Ollama API URL')
    args = parser.parse_args()

    queen_endpoints = [e.strip() for e in args.queens.split(',')]

    # Create and start the RajaBee
    raja = RajaBee(
        model_name=args.model,
        ollama_url=args.ollama_url,
        queen_endpoints=queen_endpoints
    )

    if not raja.start():
        print("Failed to start RajaBee. No Queens available!")
        sys.exit(1)

    total_workers = sum(c.get('total_workers', 1) for c in raja.queen_capabilities.values())

    print(f"\n{'='*60}")
    print(f"  Raja HTTP Wrapper running on port {args.port}")
    print(f"  Model: {args.model}")
    print(f"  Queens: {len(raja.queen_capabilities)}")
    print(f"  Total workers (across all Queens): {total_workers}")
    print(f"  Endpoints:")
    print(f"    POST http://localhost:{args.port}/process")
    print(f"    GET  http://localhost:{args.port}/capabilities")
    print(f"    GET  http://localhost:{args.port}/health")
    print(f"{'='*60}\n")

    app.run(host='0.0.0.0', port=args.port, debug=False)


if __name__ == '__main__':
    main()
