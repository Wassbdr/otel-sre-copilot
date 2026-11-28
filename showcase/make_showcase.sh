#!/usr/bin/env bash
# Rebuild showcase/ (demo.gif, demo.mp4, poster.png, showcase.json) from a clean clone.
#
# Requires Python 3.12 or uv, VHS 0.10+, ttyd and FFmpeg. Runs offline against recorded results.
set -euo pipefail
cd "$(dirname "$0")/.."
export RANDOM_SEED=42 NUMPY_SEED=42 CHAOS_SEED=42

if [[ ! -x .venv/bin/python ]]; then
  if command -v uv >/dev/null; then uv venv -q -p 3.12 .venv && uv pip install -q -p .venv -e ".[dev]"
  else "$(command -v python3.12 || command -v python3)" -m venv .venv && .venv/bin/pip install -q -e ".[dev]"; fi
fi
PY=.venv/bin/python
if ! "$PY" -c 'import matplotlib' 2>/dev/null; then
  echo 'Install the showcase dependencies with uv pip install -e ".[dev]".' >&2
  exit 1
fi
for dependency in vhs ttyd ffmpeg; do
  if ! command -v "$dependency" >/dev/null; then
    echo "Install $dependency before rebuilding the showcase." >&2
    exit 1
  fi
done

summary="results/final-summary.json"
"$PY" -m eval.final_report --summary "$summary"
"$PY" showcase/make_poster.py "$summary"
"$PY" showcase/make_showcase_json.py "$summary"
PATH="$PWD/.venv/bin:$PATH" vhs showcase/demo.tape
