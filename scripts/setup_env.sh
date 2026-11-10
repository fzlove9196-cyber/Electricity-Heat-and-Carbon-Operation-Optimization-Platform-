#!/usr/bin/env bash
# Create a local virtualenv and install Python dependencies.
# Usage: ./scripts/setup_env.sh
# Optional: PYTHON=python3.13 ./scripts/setup_env.sh
#           LOCK=1 ./scripts/setup_env.sh   # install the pinned lock file
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: $PY not found. Install Python 3.11+ (3.13.5 was used on the packaging host)." >&2
  exit 1
fi
echo "Using $($PY --version 2>&1) at $(command -v "$PY")"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "Creating $ROOT/.venv"
  "$PY" -m venv "$ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install --upgrade pip wheel setuptools

# Install CPU PyTorch first so later requirements do not pull a large CUDA wheel
# when no NVIDIA GPU is present. Safe to skip if you already have a GPU build.
if ! python -c "import torch" >/dev/null 2>&1; then
  echo "Installing CPU torch from https://download.pytorch.org/whl/cpu (override by installing torch first)."
  python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
fi

if [ "${LOCK:-0}" = "1" ]; then
  echo "Installing pinned dependencies from requirements-lock.txt"
  python -m pip install -r "$ROOT/requirements-lock.txt" --extra-index-url https://download.pytorch.org/whl/cpu
else
  echo "Installing dependencies from requirements.txt"
  python -m pip install -r "$ROOT/requirements.txt"
fi

if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Wrote .env from .env.example (LLM_MOCK=1). Edit locally; do not commit .env."
fi

echo
echo "Environment ready."
echo "  Activate:  source $ROOT/.venv/bin/activate"
echo "  Start:     ./start.sh          # Mock mode, http://127.0.0.1:8080"
echo "  Tests:     python -m pytest -q tests/"
echo "  Optional tools (not installed by this script): octave-cli, omc, pvpython"
echo "  See docs/ENVIRONMENT.md for versions, solvers, and external software."
