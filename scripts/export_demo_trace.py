"""Copy one recorded agent run to examples/ as the offline `make demo` trace.

Takes repeat 0 (the first run, not the best one) of the checkout pod-crash snapshot.

    python scripts/export_demo_trace.py --run-id bench-20261127T...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.scenario_runner import trace_path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--method", default="agent")
    parser.add_argument("--scenario-id", default="checkout-pod_crash-seed42")
    parser.add_argument("--repeat", type=int, default=0)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "examples" / "checkout-pod-crash.trace.json")
    args = parser.parse_args()
    src = trace_path(args.run_id, args.scenario_id, args.method, args.repeat)
    trace = json.loads(src.read_text())
    trace["recorded_in_run"] = args.run_id
    trace["repeat"] = args.repeat
    snap = Path(trace["snapshot_dir"])
    trace["snapshot_dir"] = str(snap.relative_to(ROOT)) if snap.is_absolute() else str(snap)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(trace, indent=2) + "\n")


if __name__ == "__main__":
    main()
