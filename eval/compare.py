"""Compare agent vs baselines across all metrics.

Reads the latest (or specified) run artifacts and prints a comparison table.
Generates results/baseline_comparison.md.

Usage:
    python -m eval.compare
    python -m eval.compare --run-id 20240115T143000Z
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

_ARTIFACTS_DIR = Path("artifacts")
_RESULTS_DIR = Path("results")

_METRIC_HEADERS = [
    ("Acc@1", "accuracy_at_1"),
    ("Acc@3", "accuracy_at_3"),
    ("MRR", "mrr"),
    ("FT Acc", "fault_type_correct"),
    ("Grounding", "grounding_score"),
    ("Latency(s)", "latency_s"),
    ("Tokens", "total_tokens"),
]

_METHODS = ["random", "zscore", "composite_zscore", "agent"]


def load_results(run_id: str) -> dict[str, list[dict[str, Any]]]:
    """Load per-scenario results for all methods from a run."""
    raw_path = _ARTIFACTS_DIR / run_id / "raw_results.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"No raw_results.json for run_id={run_id}")

    with open(raw_path) as f:
        raw = json.load(f)

    methods: dict[str, list[dict[str, Any]]] = {m: [] for m in _METHODS}
    for scenario in raw:
        if "error" in scenario:
            continue
        for method in _METHODS:
            if method == "agent" and scenario.get("agent_runs"):
                methods[method].extend(
                    r for r in scenario["agent_runs"] if isinstance(r, dict) and "error" not in r
                )
            elif method in scenario:
                methods[method].append(scenario[method])

    return methods


def aggregate(results: list[dict[str, Any]]) -> dict[str, float]:
    if not results:
        return {}
    n = len(results)
    out = {}
    for _, key in _METRIC_HEADERS:
        vals = [r.get(key) or 0.0 for r in results]
        out[key] = sum(vals) / n
    return out


def render_table(aggregated: dict[str, dict[str, float]]) -> str:
    headers = ["Method"] + [h for h, _ in _METRIC_HEADERS]
    col_widths = [max(len(h), 18) for h in headers]
    col_widths[0] = 22

    def row(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(cells)) + " |"

    sep = "|-" + "-|-".join("-" * col_widths[i] for i in range(len(headers))) + "-|"

    lines = [row(headers), sep]
    method_labels = {
        "random": "Random",
        "zscore": "Z-score error_rate",
        "composite_zscore": "Composite Z-score",
        "agent": "**SRE-Copilot**",
    }
    for method in _METHODS:
        agg = aggregated.get(method, {})
        if not agg:
            lines.append(row([method_labels.get(method, method)] + ["—"] * len(_METRIC_HEADERS)))
            continue

        cells = [method_labels.get(method, method)]
        for _, key in _METRIC_HEADERS:
            v = agg.get(key, 0.0)
            if key == "total_tokens":
                cells.append(f"{v:,.0f}")
            elif key == "latency_s":
                cells.append(f"{v:.1f}s")
            else:
                cells.append(f"{v:.3f}")
        lines.append(row(cells))

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare agent vs baselines")
    parser.add_argument("--run-id", default="", help="Run ID to compare (default: latest)")
    args = parser.parse_args()

    # Find run_id
    if args.run_id:
        run_id = args.run_id
    else:
        from eval.report import latest_run_id

        run_id = latest_run_id()
        if not run_id:
            print("No eval runs found. Run: make eval && make eval-baselines")
            sys.exit(1)

    print(f"\nComparing run: {run_id}")
    methods = load_results(run_id)

    aggregated = {method: aggregate(results) for method, results in methods.items()}

    table = render_table(aggregated)
    print("\n" + table + "\n")

    # Write to results/
    _RESULTS_DIR.mkdir(exist_ok=True)
    with open(_RESULTS_DIR / "baseline_comparison.md", "w") as f:
        f.write(f"# Baseline Comparison — run: {run_id}\n\n")
        f.write(table)
        f.write("\n\n## Notes\n")
        config_path = _ARTIFACTS_DIR / run_id / "config.json"
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        f.write(f"- Model: {config.get('model')} ({config.get('repeats', 1)} runs/snapshot)\n")
        f.write(f"- Seed: {config.get('seed', 42)}\n")
        f.write("- Grounding score: fraction of evidence items verified against tool_calls_log\n")
        f.write("- Random baseline grounding_score=0.0 by design (no evidence items)\n")
        f.write("- Agent rows average every repeated run; see results/benchmark.md for variance\n")
        f.write(f"- Reproduce: `python -m eval.compare --run-id {run_id}`\n")

    print("Written to: results/baseline_comparison.md")


if __name__ == "__main__":
    main()
