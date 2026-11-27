from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from collections.abc import Sequence
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import structlog

from eval.scenario_runner import (
    BASELINE_METHODS,
    _metrics_from_trace,
    discover_snapshots,
    run_scenario,
    trace_path,
    write_json_atomic,
)
from src.agent.llm import llm_settings

log = structlog.get_logger()
LLM_METHODS = ("agent", "react", "agent_no_prior")
METHODS = LLM_METHODS + BASELINE_METHODS
ACCURACY = ("accuracy_at_1", "accuracy_at_3", "service_at_1", "service_at_3")
MEANS = ACCURACY + ("latency_s", "llm_calls", "total_tokens", "cost_usd", "rate_limit_wait_s")
LABELS = {
    "agent": "SRE-Copilot",
    "agent_no_prior": "SRE-Copilot without anomaly prior",
    "react": "ReAct without grounding verifier in the agent",
    "baro": "RCAEval BARO (metrics)",
    "nsigma": "RCAEval N-Sigma (metrics)",
    "zscore": "Error-rate z-score",
    "composite_zscore": "Composite z-score",
    "random": "Random",
}


def _snapshot_hash(snapshot: Path) -> str:
    entries = [
        (str(p.relative_to(snapshot)), hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(snapshot.rglob("*")) if p.is_file()
    ]
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def _snapshot_set(
    scenario_dirs: Sequence[Path], split: str, run_dir: Path, repeats: int,
    snapshot_set_from: str | None = None,
    recorded_from: str | None = None,
) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    settings = llm_settings()
    setup = {
        "model": settings.model,
        "base_url": settings.base_url,
        "repeats": repeats,
        "split": split,
        "random_seed": int(os.getenv("RANDOM_SEED", "42")),
    }
    if recorded_from:
        setup["recorded_from"] = recorded_from
    if manifest_path.exists():
        manifest: dict[str, Any] = json.loads(manifest_path.read_text())
        if (any(manifest.get(key) != value for key, value in setup.items())
                or manifest.get("recorded_from") != recorded_from):
            raise ValueError("Benchmark configuration changed; choose a new BENCH_RUN_ID.")
        for snapshot in manifest["snapshots"]:
            if _snapshot_hash(Path(snapshot["path"])) != snapshot["sha256"]:
                raise ValueError(
                    f"Snapshot {snapshot['path']} changed; choose a new BENCH_RUN_ID."
                )
        return manifest

    if recorded_from:
        source = Path("artifacts") / recorded_from / "config.json"
        if not source.is_file():
            raise ValueError(f"Missing recorded run config: {source}.")
        config = json.loads(source.read_text())
        if config["model"] != settings.model or config["repeats"] != repeats:
            raise ValueError("The recorded run must use the same model and repeat count.")
        paths = sorted(Path(path) for path in config["snapshots"])
    elif snapshot_set_from:
        source = Path("artifacts") / snapshot_set_from / "manifest.json"
        if not source.is_file():
            raise ValueError(f"Missing reference snapshot manifest: {source}.")
        reference = json.loads(source.read_text())
        if any(reference.get(key) != setup[key] for key in ("split", "model", "repeats")):
            raise ValueError("The reference run must use the same split, model and repeat count.")
        paths = [Path(snapshot["path"]) for snapshot in reference["snapshots"]]
        for path, snapshot in zip(paths, reference["snapshots"], strict=True):
            if _snapshot_hash(path) != snapshot["sha256"]:
                raise ValueError(f"Reference snapshot {path} changed; rerun on a new snapshot set.")
    else:
        paths = sorted({
            path for directory in scenario_dirs for path in discover_snapshots(directory)
        })
    snapshots = []
    for path in paths:
        truth = json.loads((path / "ground_truth.json").read_text())
        if split == "held-out" and truth.get("split") != "held-out":
            continue
        if split == "development" and truth.get("split") == "held-out":
            continue
        snapshots.append({
            "path": str(path),
            "scenario_id": truth.get("scenario_id", path.name),
            "sha256": _snapshot_hash(path),
        })
    if not snapshots:
        raise ValueError(f"No validated {split} snapshots found. Capture them before benchmarking.")
    manifest = {
        **setup,
        "agent_variant": "agent_full",
        "snapshots": snapshots,
        "hardware": (config["hardware"] if recorded_from else
                     f"{platform.machine()}, {os.cpu_count()} vCPU, {platform.system()}, no GPU"),
    }
    write_json_atomic(manifest_path, manifest)
    return manifest


def _measure(
    run_id: str, snapshot: dict[str, Any], method: str, repeat: int,
    agent_variant: str, recorded_from: str | None = None,
) -> dict[str, Any]:
    runner_method = agent_variant if method == "agent" else method
    trace = trace_path(run_id, snapshot["scenario_id"], runner_method, repeat)
    checkpoint = trace.with_name("metrics.json")
    if checkpoint.exists():
        result: dict[str, Any] = json.loads(checkpoint.read_text())
        return result
    if recorded_from and method == "agent":
        recorded = trace_path(recorded_from, snapshot["scenario_id"], "agent", repeat)
        if not recorded.is_file():
            raise ValueError(f"Missing recorded trace: {recorded}. No live fallback.")
        if json.loads(recorded.read_text())["model"] != llm_settings().model:
            raise ValueError(f"Recorded trace {recorded} uses a different model.")
        result = _metrics_from_trace(recorded)
    elif method in LLM_METHODS and trace.exists():
        if json.loads(trace.read_text())["model"] != llm_settings().model:
            raise ValueError("Recorded trace uses a different model; choose a new BENCH_RUN_ID.")
        result = _metrics_from_trace(trace)
    else:
        mode = "baselines-only" if method in BASELINE_METHODS else "replay"
        result = run_scenario(
            Path(snapshot["path"]), mode, run_id, repeat, method=runner_method,
        )[runner_method]
    write_json_atomic(checkpoint, result)
    return result


def summarize_rows(
    rows: list[dict[str, Any]], repeats: int, snapshot_count: int,
) -> dict[str, Any]:
    good = [r for r in rows if "error" not in r]
    summary: dict[str, Any] = {"completed": len(good), "expected": repeats * snapshot_count}
    for metric in MEANS:
        values = [r[metric] for r in good if r.get(metric) is not None]
        summary[metric] = mean(values) if values else None
    repeats_done = [
        [r for r in good if r["repeat"] == repeat]
        for repeat in range(repeats)
    ]
    for metric in ACCURACY:
        scores = [
            mean(row[metric] for row in group)
            for group in repeats_done if len(group) == snapshot_count
        ]
        summary[f"{metric}_std"] = pstdev(scores) if len(scores) > 1 else None
    total = sum(r.get("evidence_count") or 0 for r in good)
    verified = sum(r.get("verified_evidence_count") or 0 for r in good)
    summary["evidence_count"] = total
    summary["verified_evidence_count"] = verified
    summary["grounding_score"] = verified / total if total else None
    return summary


def _format(value: float | None, spec: str) -> str:
    return format(value, spec) if value is not None else "n/a"


def _report(path: Path, iteration: dict[str, Any]) -> None:
    history_path = path / "results.json"
    history = json.loads(history_path.read_text()) if history_path.exists() else []
    prior_index = next(
        (i for i, r in enumerate(history) if r["run_id"] == iteration["run_id"]),
        len(history),
    )
    if prior_index < len(history):
        previous = history.pop(prior_index)
        for key in ("methods", "rows"):
            iteration[key] = {**previous[key], **iteration[key]}
    prior = next((
        r for r in reversed(history[:prior_index])
        if all(r["setup"][k] == iteration["setup"][k] for k in ("model", "snapshots", "repeats"))
        and r["methods"].get("agent", {}).get("completed")
        == r["methods"].get("agent", {}).get("expected")
        and r["methods"].get("agent")
    ), None)
    agent = iteration["methods"].get("agent")
    if prior and agent and agent["completed"] == agent["expected"]:
        iteration["delta"] = {
            k: agent[k] - prior["methods"]["agent"][k]
            for k in ACCURACY
        }
        iteration["compared_to"] = prior["run_id"]
    history.insert(prior_index, iteration)
    write_json_atomic(history_path, history)

    lines = ["# Benchmark results", "",
             "Top-k is the fraction of true causes covered within the first k predictions. "
             "Strict accuracy requires both service and fault type. Grounding is matched "
             "citations divided by citations made; no citations is n/a. Latency excludes rate "
             "limit waits; cached responses retain the original request duration.", "",
             "[RCAEval](https://github.com/phamquiluan/RCAEval) BARO and N-Sigma use the "
             "maximum incident value after median/IQR or mean/standard-deviation scaling. "
             "The table projects ranked metrics to unique services and maps the top signal "
             "for each service to a fault type. This is a metrics-only comparison.", ""]
    for run in history:
        setup = run["setup"]
        lines.extend([
            f"## {run['change']} ({run['run_id']})", "",
            f"{len(setup['snapshots'])} Astronomy Shop snapshots ({setup['split']}); "
            f"{setup['repeats']} runs per method; {setup['model']}; {setup['hardware']}.", "",
            "| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | "
            "Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for method in (*LLM_METHODS, "nsigma", "composite_zscore", "baro", "zscore", "random"):
            if method not in run["methods"]:
                continue
            m = run["methods"][method]
            label = LABELS[method]
            if method == "agent" and setup.get("recorded_from"):
                label += f" (recorded: {setup['recorded_from']})"
            cells = [label, f"{m['completed']}/{m['expected']}"]
            cells.extend(_format(m[key], ".1%") for key in ACCURACY)
            cells.extend([
                _format(m["grounding_score"], ".1%"),
                str(m["evidence_count"]),
                _format(m.get("llm_calls"), ".1f"),
                _format(m["total_tokens"], ",.0f"),
                _format(m["latency_s"], ".3f"),
                _format(m["cost_usd"], ".4f"),
            ])
            lines.append("| " + " | ".join(cells) + " |")
        if run.get("delta"):
            lines.extend(["", f"Change against {run['compared_to']}:", "",
                          "| Change | Metric | Delta |", "| --- | --- | ---: |"])
            for key, label in zip(
                ACCURACY, ("Top-1", "Top-3", "Service top-1", "Service top-3"), strict=True,
            ):
                lines.append(f"| {run['change']} | {label} | {run['delta'][key] * 100:+.1f} pp |")
        lines.append("")
    (path / "results.md").write_text("\n".join(lines))


def run(args: argparse.Namespace) -> bool:
    if args.repeats < 1:
        raise ValueError("--repeats must be at least one.")
    max_snapshots = getattr(args, "max_snapshots", None)
    if max_snapshots is not None and max_snapshots < 1:
        raise ValueError("--max-snapshots must be at least one.")
    if not args.run_id or Path(args.run_id).name != args.run_id or args.run_id in {".", ".."}:
        raise ValueError("Use a single directory name for BENCH_RUN_ID.")
    recorded_from = getattr(args, "recorded_from", None)
    if recorded_from and (
        Path(recorded_from).name != recorded_from or recorded_from in {".", "..", args.run_id}
        or any(method in {"react", "agent_no_prior"} for method in args.methods)
        or getattr(args, "snapshot_set_from", None)
    ):
        raise ValueError("Use a different recorded run ID with agent and/or statistical methods.")
    setup = _snapshot_set(
        args.scenario_dir, args.split, Path("artifacts") / args.run_id,
        args.repeats, getattr(args, "snapshot_set_from", None), recorded_from,
    )
    rows: dict[str, list[dict[str, Any]]] = {m: [] for m in args.methods}
    methods_order = [method for method in (*BASELINE_METHODS, *LLM_METHODS) if method in rows]

    def report_progress() -> dict[str, Any]:
        summary = {
            m: summarize_rows(r, args.repeats, len(setup["snapshots"])) for m, r in rows.items()
        }
        _report(args.output_dir, {
            "run_id": args.run_id, "change": args.change, "setup": setup, "methods": summary,
            "rows": rows,
        })
        return summary

    for snapshot in setup["snapshots"][:max_snapshots]:
        for repeat in range(args.repeats):
            for method in methods_order:
                try:
                    result = _measure(
                        args.run_id, snapshot, method, repeat, setup.get("agent_variant", "agent"),
                        recorded_from,
                    )
                except Exception as error:
                    log.error("benchmark_item_failed", method=method,
                              snapshot=snapshot["path"], repeat=repeat, error=type(error).__name__)
                    result = {"error": type(error).__name__}
                rows[method].append({**result, **snapshot, "repeat": repeat})
            methods = report_progress()
    log.info("benchmark_report", path=str(args.output_dir / "results.md"), run_id=args.run_id)
    return all(v["completed"] == v["expected"] for v in methods.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare RCA methods on recorded telemetry.")
    parser.add_argument("--scenario-dir", type=Path, action="append")
    parser.add_argument(
        "--split", choices=["development", "held-out", "all"], default="development",
    )
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=METHODS)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--snapshot-set-from", help="Pin snapshots to an existing run manifest.")
    parser.add_argument("--recorded-from", help="Re-score recorded agent traces without LLM calls.")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-snapshots", type=int, help="Pause after this many snapshots.")
    parser.add_argument("--output-dir", type=Path, default=Path("benchmarks"))
    parser.add_argument("--change", default="Baseline")
    args = parser.parse_args()
    args.scenario_dir = args.scenario_dir or [Path("scenarios/mvp"), Path("scenarios/extended")]
    try:
        complete = run(args)
    except ValueError as error:
        parser.error(str(error))
    if not complete and args.max_snapshots is None:
        parser.exit(1, "Incomplete benchmark. Repeat with the same BENCH_RUN_ID.\n")


if __name__ == "__main__":
    main()
