#!/usr/bin/env bash
# Rebuild showcase/ (demo.gif, demo.mp4, poster.png, showcase.json) from a clean clone.
#
# Requirements: python >= 3.12 (or uv), vhs >= 0.10 (+ ttyd, ffmpeg) for the terminal recording,
#               ffmpeg. No GPU, no cluster, no API key for the default (replay) path.
# Optional:     NIM_API_KEY or LLM_API_KEY + RERUN_BENCHMARK=1 to re-measure the agent
#               (3 runs per snapshot, ~1 h on the NIM free tier) instead of re-reporting the
#               committed run in artifacts/.
# Seeds:        baselines RANDOM_SEED=42; snapshots are the committed Chaos Mesh captures
#               (seeds 42 and 7); LLM temperature 0.
set -euo pipefail
cd "$(dirname "$0")/.."
export RANDOM_SEED=42 NUMPY_SEED=42 CHAOS_SEED=42

if [[ ! -x .venv/bin/python ]]; then
  if command -v uv >/dev/null; then uv venv -q -p 3.12 .venv && uv pip install -q -p .venv -e ".[dev]"
  else "$(command -v python3.12 || command -v python3)" -m venv .venv && .venv/bin/pip install -q -e ".[dev]"; fi
fi
PY=.venv/bin/python
RUN_ID="${RUN_ID:-$(cat results/RUN_ID)}"

if [[ "${RERUN_BENCHMARK:-0}" == "1" ]]; then
  RUN_ID="bench-$(date -u +%Y%m%dT%H%M%SZ)"
  "$PY" -m eval.scenario_runner --mode benchmark --repeats 3 --run-id "$RUN_ID"
  echo "$RUN_ID" > results/RUN_ID
  "$PY" scripts/export_demo_trace.py --run-id "$RUN_ID"
fi

# Baselines are deterministic: re-run them and check they match the committed run exactly.
"$PY" -m eval.scenario_runner --mode baselines-only --run-id "verify-baselines" \
  --snapshot-run-id "$RUN_ID" >/dev/null
"$PY" scripts/check_baselines.py "artifacts/verify-baselines" "artifacts/$RUN_ID"
rm -rf artifacts/verify-baselines

"$PY" -m eval.report --run-id "$RUN_ID"
"$PY" -m eval.compare --run-id "$RUN_ID" >/dev/null
"$PY" showcase/make_poster.py results/summary.json
"$PY" showcase/make_showcase_json.py results/summary.json

if command -v vhs >/dev/null; then
  PATH="$PWD/.venv/bin:$PATH" vhs showcase/demo.tape
else
  echo "vhs not found: skipped demo.gif / demo.mp4 (https://github.com/charmbracelet/vhs)" >&2
fi
ls -la showcase/
