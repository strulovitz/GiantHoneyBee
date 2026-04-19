#!/usr/bin/env bash
# smoke_launch.sh — Launch 4 bee processes for the multimedia smoke test.
#
# Usage:
#   ./scripts/smoke_launch.sh <swarm_id>
#
# Logs go to ~/multimedia_setup_logs/smoke_photo_<timestamp>/
# PIDs are saved to /tmp/smoke_bee_pids.txt for later cleanup.

set -euo pipefail

SWARM_ID="${1:?Usage: $0 <swarm_id>}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_DIR="${HOME}/multimedia_setup_logs/smoke_photo_${TIMESTAMP}"
mkdir -p "${LOG_DIR}"

echo "Log directory: ${LOG_DIR}"
echo "Swarm ID: ${SWARM_ID}"

GBEE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# honeycomb-venv has ollama, PIL, requests — the packages the bee clients need
PYTHON="${HOME}/honeycomb-venv/bin/python"

if [ ! -f "${PYTHON}" ]; then
    echo "ERROR: ${PYTHON} not found. Cannot launch bees."
    exit 1
fi

echo "Python: ${PYTHON}"

SERVER="http://localhost:8877"
OLLAMA_URL="http://localhost:11434"
PASSWORD="smoke_pass_2026"
POLL_INTERVAL=3

PID_FILE="/tmp/smoke_bee_pids.txt"
> "${PID_FILE}"   # truncate

launch() {
    local ROLE="$1"
    local SCRIPT="$2"
    local USERNAME="$3"
    local MODEL="$4"
    local LOG="${LOG_DIR}/${ROLE}.log"

    echo "Launching ${ROLE} (${SCRIPT})..."
    "${PYTHON}" -u "${GBEE_DIR}/${SCRIPT}" \
        --server "${SERVER}" \
        --swarm-id "${SWARM_ID}" \
        --username "${USERNAME}" \
        --password "${PASSWORD}" \
        --model "${MODEL}" \
        --ollama-url "${OLLAMA_URL}" \
        --poll-interval "${POLL_INTERVAL}" \
        > "${LOG}" 2>&1 &

    local PID=$!
    echo "${PID}" >> "${PID_FILE}"
    echo "  ${ROLE} PID: ${PID}  log: ${LOG}"
}

# Launch all 4 tiers
launch "raja"        "raja_bee.py"            "smoke_raja"   "qwen3.5:9b"
launch "giant_queen" "giant_queen_client.py"  "smoke_gq"     "qwen3-vl:8b"
launch "dwarf_queen" "dwarf_queen_client.py"  "smoke_dq"     "gemma3:4b"
launch "worker"      "worker_client.py"       "smoke_worker" "qwen3.5:0.8b"

echo ""
echo "All 4 bee processes launched."
echo "PIDs saved to: ${PID_FILE}"
echo "Logs in:       ${LOG_DIR}/"
echo ""
echo "To stop all bees:"
echo "  kill \$(cat ${PID_FILE})"
