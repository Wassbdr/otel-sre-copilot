#!/usr/bin/env bash
# Capture every MVP scenario for each seed against a running `make up` cluster.
# Usage: scripts/capture_matrix.sh [seed ...]       (default seeds: 42 7)
# Between captures we wait COOLDOWN_S so the next capture's pre-fault baseline window
# (BASELINE_MIN minutes) never overlaps the previous fault or its recovery.
set -uo pipefail

SEEDS=("$@")
[[ ${#SEEDS[@]} -eq 0 ]] && SEEDS=(42 7)
SCENARIO_DIR="${SCENARIO_DIR:-scenarios/mvp}"
BASELINE_MIN="${BASELINE_MIN:-8}"
COOLDOWN_S="${COOLDOWN_S:-$((BASELINE_MIN * 60))}"
PYTHON="${PYTHON:-$([[ -x .venv/bin/python ]] && echo .venv/bin/python || echo python3)}"

first=1
for seed in "${SEEDS[@]}"; do
  for scenario in "$SCENARIO_DIR"/*.yaml; do
    if [[ $first -eq 0 ]]; then
      echo "==> cooldown ${COOLDOWN_S}s"
      sleep "$COOLDOWN_S"
    fi
    first=0
    echo "==> $(date -u +%FT%TZ) seed=$seed scenario=$scenario"
    "$PYTHON" scripts/inject_and_snapshot.py --scenario "$scenario" --seed "$seed" \
      --baseline-minutes "$BASELINE_MIN" || echo "!! capture failed: $scenario seed=$seed"
  done
done
