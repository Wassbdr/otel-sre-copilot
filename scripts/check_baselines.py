"""Fail if freshly re-run baselines differ from a committed run (they are deterministic).

    python scripts/check_baselines.py artifacts/<fresh-run> artifacts/<committed-run>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

KEYS = ("predicted_service_top1", "accuracy_at_1", "accuracy_at_3", "mrr")
METHODS = ("random", "zscore", "composite_zscore")


def _index(run_dir: Path) -> dict[str, dict[str, object]]:
    rows = json.loads((run_dir / "raw_results.json").read_text())
    return {str(r.get("scenario_id")): r for r in rows if "error" not in r}


def main(fresh: Path, committed: Path) -> int:
    a, b = _index(fresh), _index(committed)
    diffs = []
    for sid in sorted(set(a) | set(b)):
        if sid not in a or sid not in b:
            diffs.append(f"{sid}: present in only one run")
            continue
        for m in METHODS:
            ra, rb = a[sid].get(m, {}), b[sid].get(m, {})
            assert isinstance(ra, dict) and isinstance(rb, dict)
            for k in KEYS:
                if ra.get(k) != rb.get(k):
                    diffs.append(f"{sid} {m}.{k}: fresh={ra.get(k)} committed={rb.get(k)}")
    for d in diffs:
        sys.stderr.write(d + "\n")
    sys.stdout.write(f"baselines reproduced: {len(a)} snapshots, {len(diffs)} differences\n")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
