"""
DwarfQueen HTTP Wrapper — Expose an existing Queen Bee as an HTTP endpoint
==========================================================================
Named after Apis florea (Red Dwarf Honey Bee). The DwarfQueen is the lowest-level
coordinator — the ONLY queen that has Workers directly under her.

This thin wrapper turns any HoneycombOfAI Queen Bee into an HTTP service
that a RajaBee or GiantQueen can call. The Queen code stays COMPLETELY untouched.

Endpoints:
    POST /process     — Send a task, get a result
    GET  /capabilities — Report how many workers, models, avg response time
"""

import sys
import os
import time
import argparse
from flask import Flask, request, jsonify

# Add HoneycombOfAI to path so we can import Queen and Worker
HONEYCOMB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'HoneycombOfAI')
sys.path.insert(0, HONEYCOMB_PATH)

from queen_bee import QueenBee
from worker_bee import WorkerBee

app = Flask(__name__)

# These get set in main()
dwarf_queen = None
dwarf_queen_stats = {"tasks_completed": 0, "total_time": 0.0}


@app.route('/process', methods=['POST'])
def process_task():
    """Accept a task, run it through the DwarfQueen, return the result."""
    data = request.get_json()
    task = data.get('task', '')

    if not task:
        return jsonify({"error": "No task provided"}), 400

    start = time.time()
    result = dwarf_queen.process_nectar(task)
    elapsed = time.time() - start

    dwarf_queen_stats["tasks_completed"] += 1
    dwarf_queen_stats["total_time"] += elapsed

    return jsonify({"result": result, "time": round(elapsed, 2)})


@app.route('/capabilities', methods=['GET'])
def capabilities():
    """Report this DwarfQueen's capabilities so the RajaBee/GiantQueen can split work proportionally."""
    avg_time = 0.0
    if dwarf_queen_stats["tasks_completed"] > 0:
        avg_time = dwarf_queen_stats["total_time"] / dwarf_queen_stats["tasks_completed"]

    return jsonify({
        "total_workers": len(dwarf_queen.workers),
        "model": dwarf_queen.model_name,
        "tasks_completed": dwarf_queen_stats["tasks_completed"],
        "avg_response_time": round(avg_time, 2)
    })


@app.route('/health', methods=['GET'])
def health():
    """Simple health check."""
    return jsonify({"status": "alive", "workers": len(dwarf_queen.workers)})


def main():
    global dwarf_queen

    parser = argparse.ArgumentParser(description="DwarfQueen HTTP Wrapper — expose a Queen Bee as HTTP (lowest level, has Workers)")
    parser.add_argument('--port', type=int, default=5000, help='Port to listen on')
    parser.add_argument('--model', type=str, default='qwen2.5:1.5b', help='Ollama model for the DwarfQueen')
    parser.add_argument('--workers', type=int, default=1, help='Number of local Worker Bees')
    parser.add_argument('--worker-model', type=str, default=None, help='Model for workers (default: same as DwarfQueen)')
    parser.add_argument('--ollama-url', type=str, default='http://localhost:11434', help='Ollama API URL')
    args = parser.parse_args()

    worker_model = args.worker_model or args.model

    # Create the DwarfQueen (wraps the existing QueenBee from HoneycombOfAI)
    dwarf_queen = QueenBee(model_name=args.model, ollama_url=args.ollama_url)

    if not dwarf_queen.start():
        print("Failed to start DwarfQueen. Is Ollama running?")
        sys.exit(1)

    # Add local workers
    for i in range(args.workers):
        worker = WorkerBee(
            worker_id=f"W{i+1}",
            model_name=worker_model,
            ollama_url=args.ollama_url
        )
        dwarf_queen.add_worker(worker)

    print(f"\n{'='*60}")
    print(f"  DwarfQueen HTTP Wrapper running on port {args.port}")
    print(f"  Model: {args.model}")
    print(f"  Workers: {args.workers} (model: {worker_model})")
    print(f"  Endpoints:")
    print(f"    POST http://localhost:{args.port}/process")
    print(f"    GET  http://localhost:{args.port}/capabilities")
    print(f"    GET  http://localhost:{args.port}/health")
    print(f"{'='*60}\n")

    app.run(host='0.0.0.0', port=args.port, debug=False)


if __name__ == '__main__':
    main()
