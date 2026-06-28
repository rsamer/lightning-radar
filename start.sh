#!/usr/bin/env bash
# Development startup script — launches backend and frontend in parallel.
# Must be run from the repository root (this folder).
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_ENV="lightning-radar"

# Activate the conda environment
if ! conda activate "$CONDA_ENV" 2>/dev/null; then
    source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null \
        && conda activate "$CONDA_ENV"
fi

if [[ "$CONDA_DEFAULT_ENV" != "$CONDA_ENV" ]]; then
    echo "ERROR: Could not activate conda environment '$CONDA_ENV'" >&2
    exit 1
fi

echo "Starting Lightning Radar (env: $CONDA_DEFAULT_ENV)"

# Backend — must run from backend/ so relative DB path resolves correctly
cd "$REPO_ROOT/backend"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!

sleep 2

# Frontend
cd "$REPO_ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "Backend:  http://127.0.0.1:8000"
echo "Frontend: http://localhost:5173"
echo "Press Ctrl+C to stop."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
