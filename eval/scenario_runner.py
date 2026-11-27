"""Evaluation scenario runner.

Orchestrates: snapshot → run_agent(ReplayDataSource) → grounding verify → score.
Can also run baselines-only mode.

Usage (via Makefile):
    python -m eval.scenario_runner --scenario-dir scenarios/mvp --mode replay
    python -m eval.scenario_runner --scenario-dir scenarios/mvp --mode baselines-only
    python -m eval.scenario_runner --snapshot-dir snapshots/foo --mode single --print-report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

log = structlog.get_logger()

_ARTIFACTS_DIR = Path("artifacts")
_SNAPSHOTS_DIR = Path("snapshots")


def opaque_incident_id(scenario_id: str) -> str:
    """Hide the answer: snapshot ids name the faulty service and fault type."""
    return "INC-" + hashlib.sha256(scenario_id.encode()).hexdigest()[:8]


def run_scenario(
    snapshot_dir: Path,
    mode: str = "replay",
    run_id: str = "",
    repeat: int = 0,
) -> dict[str, object]:
    """Run one scenario: agent (or baseline) + grounding verify + per-scenario metrics."""
    from eval.grounding_verifier import verify
    from eval.metrics import ScenarioResult, compute_per_scenario
    from src.agent.schemas import InvestigationReport
    from src.datasources.replay import ReplayDataSource

    gt_path = snapshot_dir / "ground_truth.json"
    if not gt_path.exists():
        raise FileNotFoundError(f"ground_truth.json not found in {snapshot_dir}")

    with open(gt_path) as f:
        ground_truth: dict[str, str] = json.load(f)

    scenario_id = ground_truth.get("scenario_id", snapshot_dir.name)
    log.info("running_scenario", scenario_id=scenario_id, mode=mode)

    ds = ReplayDataSource(snapshot_dir)

    # Read window from metadata
    meta_path = snapshot_dir / "metadata.json"
    with open(meta_path) as f:
        meta = json.load(f)
    start = meta["window_start"]
    end = meta["window_end"]
    namespace = meta.get("namespace", "otel-demo")

    if mode == "baselines-only":
        return _run_baselines(ground_truth, ds, start, end, namespace, scenario_id, run_id)

    # Run agent
    from src.agent.graph import build_graph
    from src.agent.schemas import initial_state

    graph = build_graph(ds)
    from src.agent.llm import llm_settings
    state = initial_state(
        incident_id=opaque_incident_id(scenario_id),
        incident_start_ts=start,
        incident_end_ts=end,
        affected_namespace=namespace,
    )
    from src.agent.llm import rate_limit_wait_s

    rate_limit_wait_s(reset=True)
    state["_investigation_start_ts"] = datetime.now(UTC).isoformat()

    result = graph.invoke(state, {"recursion_limit": 100})
    report: InvestigationReport = result["final_report"]
    tool_calls_log: list[dict[str, Any]] = result.get("tool_calls_log", [])

    # Grounding verification (harness, not self-reported)
    grounding_result = verify(report, tool_calls_log)
    report.grounding_score = grounding_result.grounding_score

    sr = ScenarioResult(
        scenario_id=scenario_id,
        report=report,
        ground_truth=ground_truth,
        grounding_score=grounding_result.grounding_score,
    )
    per_scenario = compute_per_scenario(sr)
    per_scenario["repeat"] = repeat
    per_scenario["llm_calls"] = result.get("token_usage", {}).get("llm_calls", 0)
    per_scenario["tool_calls"] = len(tool_calls_log)
    per_scenario["rate_limit_wait_s"] = rate_limit_wait_s()

    # Save run artifacts
    if run_id:
        artifact_dir = _ARTIFACTS_DIR / run_id / "scenarios" / scenario_id / f"rep{repeat}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        with open(artifact_dir / "report.json", "w") as f:
            f.write(report.model_dump_json(indent=2))
        with open(artifact_dir / "tool_calls.jsonl", "w") as f:
            for tc in tool_calls_log:
                f.write(json.dumps(tc) + "\n")
        with open(artifact_dir / "grounding.json", "w") as f:
            json.dump({
                "grounding_score": grounding_result.grounding_score,
                "verified": grounding_result.verified_count,
                "total": grounding_result.total_count,
                "failed_items": grounding_result.failed_items,
                "has_hallucination_warning": grounding_result.has_hallucination_warning,
            }, f, indent=2)
        # Self-contained recorded trace: everything `sre-copilot-demo` needs to replay offline.
        with open(artifact_dir / "trace.json", "w") as f:
            json.dump({
                "scenario_id": scenario_id,
                "snapshot_dir": str(snapshot_dir),
                "window": {"start": start, "end": end, "namespace": namespace},
                "model": llm_settings().model,
                "ground_truth": ground_truth,
                "tool_calls": tool_calls_log,
                "report": report.model_dump(mode="json"),
                "grounding": {
                    "score": grounding_result.grounding_score,
                    "verified": grounding_result.verified_count,
                    "total": grounding_result.total_count,
                    "failed_items": grounding_result.failed_items,
                },
                "metrics": per_scenario,
            }, f, indent=2)

    if grounding_result.has_hallucination_warning:
        log.warning("hallucination_warning", scenario_id=scenario_id,
                    grounding_score=grounding_result.grounding_score)

    return {"agent": per_scenario}


def _run_baselines(
    ground_truth: dict[str, str],
    ds: object,
    start: str,
    end: str,
    namespace: str,
    scenario_id: str,
    run_id: str,
) -> dict[str, object]:
    from eval.baselines.composite_zscore import CompositeZScoreBaseline
    from eval.baselines.random_baseline import RandomBaseline
    from eval.baselines.zscore_baseline import ZScoreBaseline
    from eval.metrics import ScenarioResult, compute_per_scenario

    baselines: dict[str, Any] = {
        "random": RandomBaseline(seed=int(os.getenv("RANDOM_SEED", "42"))),
        "zscore": ZScoreBaseline(),
        "composite_zscore": CompositeZScoreBaseline(),
    }

    results: dict[str, object] = {}
    for name, baseline in baselines.items():
        report = baseline.predict(ds, start, end, namespace, scenario_id)
        # Baselines have no tool_calls_log — grounding_score is 0 (they don't produce evidence)
        report.grounding_score = 0.0
        sr = ScenarioResult(
            scenario_id=scenario_id,
            report=report,
            ground_truth=ground_truth,
            grounding_score=0.0,
        )
        results[name] = compute_per_scenario(sr)

    return results


def discover_snapshots(scenario_dir: Path) -> list[Path]:
    """All snapshots (every seed) of the scenarios defined in scenario_dir, sorted."""
    snapshot_dirs: list[Path] = []
    for scenario_yaml in sorted(scenario_dir.glob("*.yaml")):
        try:
            import yaml as _yaml
            with open(scenario_yaml) as f:
                doc = _yaml.safe_load(f)
            scenario_id = str(doc.get("metadata", {}).get("scenario_id", scenario_yaml.stem))
        except Exception:
            scenario_id = scenario_yaml.stem
        base = scenario_id.rsplit("-seed", 1)[0]
        found = sorted(
            d for d in _SNAPSHOTS_DIR.glob(f"{base}-seed*")
            if (d / "ground_truth.json").exists() and (d / "prometheus").exists()
        )
        if not found:
            log.warning("snapshot_missing", scenario=scenario_id,
                        hint=f"Run: make fault SCENARIO={scenario_yaml}")
        snapshot_dirs.extend(found)
    return snapshot_dirs


def run_all(
    scenario_dir: Path,
    mode: str,
    run_id: str = "",
    repeats: int = 1,
) -> None:
    """Run all scenarios in a directory and write aggregated results."""
    if not run_id:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    snapshot_dirs = discover_snapshots(scenario_dir)

    if not snapshot_dirs:
        log.error("no_snapshots_found", scenario_dir=str(scenario_dir))
        sys.exit(1)

    log.info("running_eval", n_scenarios=len(snapshot_dirs), mode=mode, run_id=run_id)

    all_results: list[dict[str, object]] = []
    for snap_dir in snapshot_dirs:
        with open(snap_dir / "ground_truth.json") as f:
            gt = json.load(f)
        row: dict[str, object] = {
            "snapshot_dir": str(snap_dir),
            "scenario_id": gt.get("scenario_id", snap_dir.name),
            "scenario": str(gt.get("scenario_id", snap_dir.name)).rsplit("-seed", 1)[0],
            "seed": gt.get("seed"),
            "validation_passed": gt.get("validation_passed"),
        }
        try:
            if mode in ("baselines-only", "benchmark"):
                row.update(run_scenario(snap_dir, mode="baselines-only", run_id=run_id))
            if mode in ("replay", "benchmark"):
                runs: list[object] = []
                for k in range(repeats):
                    done = (_ARTIFACTS_DIR / run_id / "scenarios" / str(row["scenario_id"])
                            / f"rep{k}" / "trace.json")
                    if done.exists():  # resume: a rerun with the same --run-id skips it
                        runs.append(json.loads(done.read_text())["metrics"])
                        continue
                    try:
                        runs.append(run_scenario(snap_dir, mode="replay", run_id=run_id,
                                                 repeat=k)["agent"])
                    except Exception as e:  # one failed LLM run must not lose the others
                        log.error("agent_run_failed", snapshot_dir=str(snap_dir), repeat=k,
                                  error=str(e))
                        runs.append({"repeat": k, "error": str(e)})
                row["agent_runs"] = runs
                ok = [r for r in runs if isinstance(r, dict) and "error" not in r]
                if ok:
                    row["agent"] = ok[0]
        except Exception as e:
            log.error("scenario_failed", snapshot_dir=str(snap_dir), error=str(e))
            row["error"] = str(e)
        all_results.append(row)
        # Write after every snapshot so a long run that dies keeps its partial results.
        _write_summary(all_results, run_id, mode, repeats, quiet=True)

    # Compute aggregate metrics
    _write_summary(all_results, run_id, mode, repeats)


def _write_summary(
    all_results: list[dict[str, object]],
    run_id: str,
    mode: str,
    repeats: int = 1,
    quiet: bool = False,
) -> None:
    import platform

    from src.agent.llm import llm_settings

    artifact_dir = _ARTIFACTS_DIR / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Write raw results
    with open(artifact_dir / "raw_results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    # If agent mode: rehydrate ScenarioResult objects for aggregate metrics
    # (simplified: read grounding from per-scenario files)
    if mode != "baselines-only" and not quiet:
        scenario_results: list[dict[str, Any]] = [
            r["agent"] for r in all_results if isinstance(r.get("agent"), dict)  # type: ignore[misc]
        ]
        _print_table(scenario_results, "Agent", run_id)

    config = {
        "run_id": run_id,
        "mode": mode,
        "model": llm_settings().model if mode != "baselines-only" else None,
        "llm_base_url": llm_settings().base_url if mode != "baselines-only" else None,
        "repeats": repeats,
        "seed": int(os.getenv("RANDOM_SEED", "42")),
        "snapshots": [r["snapshot_dir"] for r in all_results],
        "hardware": f"{platform.machine()} {os.cpu_count()} vCPU, {platform.system()}, no GPU",
        "python": platform.python_version(),
        "agent_version": "0.1.0",
        "n_scenarios": len(all_results),
        "ts": datetime.now(UTC).isoformat(),
    }
    with open(artifact_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    if not quiet:
        log.info("eval_complete", run_id=run_id, artifact_dir=str(artifact_dir))
        print(f"\nArtifacts written to: artifacts/{run_id}/")


def _print_table(results: list[dict[str, Any]], label: str, run_id: str) -> None:
    if not results:
        return
    n = len(results)
    acc1 = sum(r.get("accuracy_at_1", 0) for r in results) / n
    acc3 = sum(r.get("accuracy_at_3", 0) for r in results) / n
    mrr = sum(r.get("mrr", 0.0) for r in results) / n
    ft = sum(r.get("fault_type_correct", 0) for r in results) / n
    gs = sum(r.get("grounding_score", 0.0) for r in results) / n
    lat = sum(r.get("latency_s", 0.0) for r in results) / n
    cost = sum(r.get("cost_usd", 0.0) for r in results)

    print(f"\n{'─'*70}")
    print(f"  {label} — {n} scenarios  [run_id: {run_id}]")
    print(f"{'─'*70}")
    print(f"  Acc@1:           {acc1:.3f}")
    print(f"  Acc@3:           {acc3:.3f}")
    print(f"  MRR:             {mrr:.3f}")
    print(f"  FaultType Acc:   {ft:.3f}")
    print(f"  Grounding Score: {gs:.3f}")
    print(f"  Mean Latency:    {lat:.1f}s")
    print(f"  Total Cost:      ${cost:.4f}")
    print(f"{'─'*70}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run evaluation scenarios")
    parser.add_argument("--scenario-dir", type=Path, default=Path("scenarios/mvp"))
    parser.add_argument("--snapshot-dir", type=Path, default=None,
                        help="Single snapshot dir (use with --mode single)")
    parser.add_argument("--mode", choices=["replay", "baselines-only", "benchmark", "single"],
                        default="replay",
                        help="benchmark = baselines + agent on every snapshot")
    parser.add_argument("--repeats", type=int, default=1,
                        help="Agent runs per snapshot (variance across LLM runs)")
    parser.add_argument("--run-id", default="", help="Override run ID")
    parser.add_argument("--print-report", action="store_true")
    args = parser.parse_args()

    if args.mode == "single" and args.snapshot_dir:
        run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        result = run_scenario(args.snapshot_dir, mode="replay", run_id=run_id)
        if args.print_report:
            print(json.dumps(result, indent=2))
    else:
        run_all(args.scenario_dir, mode=args.mode, run_id=args.run_id, repeats=args.repeats)


if __name__ == "__main__":
    main()
