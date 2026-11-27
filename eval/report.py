"""Benchmark report: aggregate a run's raw_results.json into results/.

Writes
- results/summary.json    machine-readable aggregates (read by the poster and the README table)
- results/benchmark.md    headline table, per-scenario table, per-snapshot table, setup
- results/raw_results.json + results/config.json   copies of the run artifacts

Usage:
    python -m eval.report                 # latest run in artifacts/
    python -m eval.report --run-id bench-2026-11
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

_ARTIFACTS_DIR = Path("artifacts")
_RESULTS_DIR = Path("results")

METHODS = ["agent", "composite_zscore", "zscore", "random"]
LABELS = {
    "agent": "SRE-Copilot agent (LLM)",
    "composite_zscore": "Composite z-score (4 signals)",
    "zscore": "Z-score on error_rate",
    "random": "Random",
}


def load_run(run_id: str) -> list[dict[str, Any]]:
    path = _ARTIFACTS_DIR / run_id / "raw_results.json"
    if not path.exists():
        raise FileNotFoundError(f"Run artifacts not found: {path}")
    with open(path) as f:
        return json.load(f)  # type: ignore[no-any-return]


def latest_run_id() -> str | None:
    if not _ARTIFACTS_DIR.exists():
        return None
    dirs = sorted(_ARTIFACTS_DIR.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs:
        if (d / "raw_results.json").exists():
            return d.name
    return None


def _runs(row: dict[str, Any], method: str) -> list[dict[str, Any]]:
    """Every scored run of `method` on one snapshot (agent: one per repeat)."""
    if method == "agent":
        runs = row.get("agent_runs") or ([row["agent"]] if "agent" in row else [])
        return [r for r in runs if isinstance(r, dict) and "error" not in r]
    value = row.get(method)
    return [value] if isinstance(value, dict) else []


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _std(values: list[float]) -> float | None:
    return round(statistics.pstdev(values), 4) if len(values) > 1 else None


def _agg(runs: list[dict[str, Any]]) -> dict[str, Any]:
    def col(key: str) -> list[float]:
        return [float(r[key]) for r in runs if r.get(key) is not None]

    return {
        "n": len(runs),
        "accuracy_at_1": _mean(col("accuracy_at_1")),
        "accuracy_at_3": _mean(col("accuracy_at_3")),
        "mrr": _mean(col("mrr")),
        "fault_type_accuracy": _mean(col("fault_type_correct")),
        "grounding_score": _mean(col("grounding_score")),
        "latency_s": _mean(col("latency_s")),
        "latency_p50_s": round(statistics.median(col("latency_s")), 2) if runs else None,
        "tokens_per_investigation": _mean(col("total_tokens")),
        "hallucination_warnings": sum(1 for r in runs if r.get("hallucination_warning")),
    }


def summarize(raw: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in raw if "error" not in r]
    methods: dict[str, Any] = {}
    for m in METHODS:
        all_runs = [run for row in rows for run in _runs(row, m)]
        if not all_runs:
            continue
        methods[m] = _agg(all_runs)

    # Agent variance: score each repeat as a full benchmark pass, then spread across passes.
    by_repeat: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for run in _runs(row, "agent"):
            by_repeat[int(run.get("repeat", 0))].append(run)
    if by_repeat and "agent" in methods:
        passes = {k: _agg(v) for k, v in sorted(by_repeat.items())}
        methods["agent"]["repeats"] = len(passes)
        for key in ("accuracy_at_1", "accuracy_at_3", "grounding_score", "latency_s",
                    "tokens_per_investigation"):
            vals = [p[key] for p in passes.values() if p[key] is not None]
            methods["agent"][f"{key}_std_across_repeats"] = _std(vals)
            methods["agent"][f"{key}_per_repeat"] = vals

    per_scenario: dict[str, dict[str, Any]] = {}
    for scenario in sorted({str(r.get("scenario")) for r in rows}):
        srows = [r for r in rows if str(r.get("scenario")) == scenario]
        gt = srows[0].get("agent", srows[0].get("zscore", {})) if srows else {}
        per_scenario[scenario] = {
            "seeds": sorted(r.get("seed") for r in srows if r.get("seed") is not None),
            "ground_truth": {"service": gt.get("ground_truth_service"),
                             "fault_type": gt.get("ground_truth_fault_type")},
            **{m: _agg([run for row in srows for run in _runs(row, m)])
               for m in METHODS if any(_runs(row, m) for row in srows)},
        }

    per_snapshot = []
    for row in rows:
        entry: dict[str, Any] = {"scenario_id": row.get("scenario_id"), "seed": row.get("seed")}
        for m in METHODS:
            runs = _runs(row, m)
            if runs:
                entry[m] = {
                    "top1": [r.get("predicted_service_top1") for r in runs],
                    "accuracy_at_1": _mean([float(r["accuracy_at_1"]) for r in runs]),
                    "accuracy_at_3": _mean([float(r["accuracy_at_3"]) for r in runs]),
                }
        entry["ground_truth_service"] = next(
            (r.get("ground_truth_service") for m in METHODS for r in _runs(row, m)), None)
        per_snapshot.append(entry)

    return {
        "n_snapshots": len(rows),
        "n_scenarios": len(per_scenario),
        "failed_snapshots": [r.get("snapshot_dir") for r in raw if "error" in r],
        "methods": methods,
        "per_scenario": per_scenario,
        "per_snapshot": per_snapshot,
    }


def _fmt(v: float | None, pct: bool = False, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.0f}%" if pct else f"{v:.{digits}f}"


def _pm(mean: float | None, std: float | None) -> str:
    return _fmt(mean, pct=True) + (f" ± {std * 100:.0f}" if std is not None else "")


def headline_table(summary: dict[str, Any]) -> str:
    lines = [
        "| Method | Top-1 | Top-3 | Grounding | Latency / incident | Tokens / incident |",
        "|---|---|---|---|---|---|",
    ]
    for m in METHODS:
        a = summary["methods"].get(m)
        if not a:
            continue
        is_agent = m == "agent"
        top1 = _pm(a["accuracy_at_1"], a.get("accuracy_at_1_std_across_repeats"))
        top3 = _pm(a["accuracy_at_3"], a.get("accuracy_at_3_std_across_repeats"))
        grounding = _fmt(a["grounding_score"]) if is_agent else "n/a"
        latency = f"{a['latency_s']:.1f} s" if is_agent and a["latency_s"] else (
            f"{(a['latency_s'] or 0) * 1000:.0f} ms")
        tokens = f"{a['tokens_per_investigation']:,.0f}" if is_agent else "0"
        name = f"**{LABELS[m]}**" if is_agent else LABELS[m]
        lines.append(f"| {name} | {top1} | {top3} | {grounding} | {latency} | {tokens} |")
    return "\n".join(lines)


def scenario_table(summary: dict[str, Any]) -> str:
    present = [m for m in METHODS if m in summary["methods"]]
    head = "| Scenario (ground truth) | seeds | " + " | ".join(
        f"{LABELS[m].split(' (')[0]} top-1 / top-3" for m in present) + " |"
    lines = [head, "|---|---|" + "---|" * len(present)]
    for name, s in summary["per_scenario"].items():
        cells = [f"{_fmt(s[m]['accuracy_at_1'], True)} / {_fmt(s[m]['accuracy_at_3'], True)}"
                 if m in s else "—" for m in present]
        gt = s["ground_truth"]
        lines.append(f"| `{name}` ({gt['service']}, {gt['fault_type']}) | "
                     f"{','.join(map(str, s['seeds']))} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def snapshot_table(summary: dict[str, Any]) -> str:
    present = [m for m in METHODS if any(m in s for s in summary["per_snapshot"])]
    lines = ["| Snapshot | truth | " + " | ".join(f"{m} top-1" for m in present) + " |",
             "|---|---|" + "---|" * len(present)]
    for s in summary["per_snapshot"]:
        cells = [", ".join(str(x) for x in s[m]["top1"]) if m in s else "—" for m in present]
        lines.append(f"| `{s['scenario_id']}` | {s['ground_truth_service']} | "
                     + " | ".join(cells) + " |")
    return "\n".join(lines)


def setup_line(config: dict[str, Any], summary: dict[str, Any]) -> str:
    seeds = sorted({str(s) for v in summary["per_scenario"].values() for s in v["seeds"]})
    return (f"{summary['n_snapshots']} replayed Chaos Mesh snapshots ({summary['n_scenarios']} "
            f"scenarios × seeds {', '.join(seeds)}) of the OpenTelemetry Astronomy Shop; agent = "
            f"`{config.get('model')}` via NVIDIA NIM, temperature 0, "
            f"{config.get('repeats', 1)} runs per snapshot; baseline RANDOM_SEED="
            f"{config.get('seed', 42)}; {config.get('hardware', 'CPU only')}.")


def write_report(run_id: str, results_dir: Path = _RESULTS_DIR) -> dict[str, Any]:
    raw = load_run(run_id)
    config_path = _ARTIFACTS_DIR / run_id / "config.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    summary = summarize(raw)
    summary["run_id"] = run_id
    summary["setup"] = setup_line(config, summary)
    summary["config"] = config

    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    shutil.copy(_ARTIFACTS_DIR / run_id / "raw_results.json", results_dir / "raw_results.json")
    if config_path.exists():
        shutil.copy(config_path, results_dir / "config.json")

    agent = summary["methods"].get("agent", {})
    md = [
        f"# Benchmark — run `{run_id}`",
        "",
        summary["setup"],
        "",
        headline_table(summary),
        "",
        "Top-1 / top-3: the faulty service is ranked first / in the first three. "
        "Agent figures are the mean over all runs; `± x` is the standard deviation of the "
        "benchmark-level score across the repeated passes. Grounding: share of the agent's "
        "cited evidence that the external verifier matched to a tool call it really made "
        f"(< 0.8 = hallucination warning; {agent.get('hallucination_warnings', 0)} of "
        f"{agent.get('n', 0)} agent runs flagged). Latency is wall-clock per investigation, "
        "LLM calls included. Tokens = prompt + completion over every LLM call.",
        "",
        "## Per scenario",
        "",
        scenario_table(summary),
        "",
        "## Per snapshot (top-1 prediction of each run)",
        "",
        snapshot_table(summary),
        "",
        "## Reproduce",
        "",
        "```bash",
        f"python -m eval.scenario_runner --mode benchmark --repeats {config.get('repeats', 1)} "
        f"--run-id {run_id}",
        f"python -m eval.report --run-id {run_id}",
        "```",
        "",
    ]
    if summary["failed_snapshots"]:
        md += ["Failed snapshots: " + ", ".join(map(str, summary["failed_snapshots"])), ""]
    (results_dir / "benchmark.md").write_text("\n".join(md))
    return summary


README_START = "<!-- benchmark:start (written by python -m eval.report) -->"
README_END = "<!-- benchmark:end -->"


def update_readme(summary: dict[str, Any], readme: Path) -> bool:
    """Replace the README block between the benchmark markers with the measured table."""
    if not readme.exists():
        return False
    text = readme.read_text()
    if README_START not in text or README_END not in text:
        return False
    head, rest = text.split(README_START, 1)
    _, tail = rest.split(README_END, 1)
    block = (f"{README_START}\n{headline_table(summary)}\n\n<sub>{summary['setup']} "
             f"Run `{summary['run_id']}`, full tables in "
             f"[results/benchmark.md](results/benchmark.md).</sub>\n{README_END}")
    readme.write_text(head + block + tail)
    return True


def main() -> None:
    import structlog

    parser = argparse.ArgumentParser(description="Write results/ from a benchmark run")
    parser.add_argument("--run-id", default="", help="Run ID (default: latest)")
    parser.add_argument("--results-dir", type=Path, default=_RESULTS_DIR)
    parser.add_argument("--readme", type=Path, default=Path("README.md"),
                        help="README whose benchmark block is rewritten (if it has the markers)")
    args = parser.parse_args()
    run_id = args.run_id or latest_run_id()
    if not run_id:
        raise SystemExit("No run in artifacts/. Run: make benchmark")
    summary = write_report(run_id, args.results_dir)
    update_readme(summary, args.readme)
    structlog.get_logger().info("report_written", run_id=run_id, results_dir=str(args.results_dir),
                                n_snapshots=summary["n_snapshots"])


if __name__ == "__main__":
    main()
