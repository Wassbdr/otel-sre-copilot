from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from eval import bench, scenario_runner
from eval.baselines.rcaeval import rank_signal
from eval.metrics import ScenarioResult, compute_per_scenario
from src.agent.schemas import InvestigationReport, RootCauseHypothesis


def test_rcaeval_standardizes_each_point_before_taking_maximum() -> None:
    assert rank_signal([1, 3, 5], [10, 2], "baro") == 3.5
    assert rank_signal([4, 4, 4], [3, 9], "nsigma") == 5.0
    assert rank_signal([1, 3], [0, 3], "nsigma") == 1.0


def test_multifault_metrics_count_each_distinct_cause() -> None:
    hypothesis = RootCauseHypothesis(
        rank=1, service="cart", fault_type="http_abort", description="loss", confidence=0.9,
    )
    report = InvestigationReport(
        incident_id="test", investigation_start_ts="", investigation_end_ts="",
        root_causes=[hypothesis], fault_type_classification=hypothesis.fault_type,
    )
    result = compute_per_scenario(ScenarioResult(
        "test", report, {"faults": [
            {"fault_service": "cart", "fault_type": "http_abort"},
            {"fault_service": "currency", "fault_type": "cpu_stress"},
        ]}, 1.0,
    ))
    assert result["accuracy_at_1"] == result["accuracy_at_3"] == 0.5
    assert result["service_at_3"] == 0.5


def test_benchmark_resumes_only_missing_method_snapshot_repeat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scenario_runner, "_ARTIFACTS_DIR", Path("artifacts"))
    snapshots = [tmp_path / name for name in ("case-a", "case-b")]
    for path in snapshots:
        path.mkdir()
        (path / "ground_truth.json").write_text(json.dumps({"scenario_id": path.name}))
    monkeypatch.setattr(bench, "discover_snapshots", lambda _: snapshots)
    calls: list[tuple[str, str, int]] = []
    fail_at = ("case-b", "random", 1)

    def measure(
        path: Path, mode: str, run_id: str, repeat: int, *, method: str,
    ) -> dict[str, object]:
        item = (path.name, method, repeat)
        calls.append(item)
        if item == fail_at and calls.count(item) == 1:
            raise RuntimeError
        return {method: {
            **dict.fromkeys(bench.ACCURACY, 0.5),
            "evidence_count": 0, "verified_evidence_count": 0,
        }}

    monkeypatch.setattr(bench, "run_scenario", measure)
    args = argparse.Namespace(
        methods=["random", "composite_zscore"], run_id="resume", repeats=2,
        scenario_dir=[Path("scenarios")], split="development", output_dir=Path("benchmarks"),
        change="Baseline",
    )
    assert not bench.run(args)
    assert len(calls) == 8
    assert bench.run(args)
    assert calls[8:] == [fail_at]
    result = json.loads((args.output_dir / "results.json").read_text())[0]
    assert result["methods"]["random"]["completed"] == 4
    assert result["methods"]["random"]["grounding_score"] is None


def test_improved_run_pins_original_snapshot_set_and_preserves_legacy_variant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scenario_runner, "_ARTIFACTS_DIR", Path("artifacts"))
    old_snapshot = tmp_path / "old"
    old_snapshot.mkdir()
    (old_snapshot / "ground_truth.json").write_text('{"scenario_id":"old"}')
    monkeypatch.setattr(bench, "discover_snapshots", lambda _: [old_snapshot])
    original = Path("artifacts/old")
    manifest = bench._snapshot_set([Path("scenarios")], "development", original, 3)
    del manifest["agent_variant"]
    (original / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(bench, "discover_snapshots", lambda _: pytest.fail("must use manifest"))
    pinned = bench._snapshot_set(
        [], "development", Path("artifacts/new"), 3, snapshot_set_from="old",
    )
    assert pinned["snapshots"] == manifest["snapshots"]

    def run_scenario(
        path: Path, mode: str, run_id: str, repeat: int, *, method: str,
    ) -> dict[str, dict[str, str]]:
        return {method: {"method": method}}

    monkeypatch.setattr(bench, "run_scenario", run_scenario)
    for run_id, config, expected in (("old", manifest, "agent"), ("new", pinned, "agent_full")):
        row = bench._measure(
            run_id, config["snapshots"][0], "agent", 0, config.get("agent_variant", "agent"),
        )
        assert row["method"] == expected


def test_recorded_benchmark_has_no_live_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(scenario_runner, "_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(bench, "run_scenario", lambda *a, **k: pytest.fail("no live call"))
    with pytest.raises(ValueError, match="No live fallback"):
        bench._measure("test", {"scenario_id": "missing"}, "agent", 0, "agent_full", "recorded")


def test_live_methods_interleave_for_each_snapshot_and_repeat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    snapshots = [{"path": name, "scenario_id": name} for name in ("case-a", "case-b")]
    monkeypatch.setattr(bench, "_snapshot_set", lambda *args: {"snapshots": snapshots})
    monkeypatch.setattr(bench, "_report", lambda *args: None)
    observed: list[tuple[str, str, int]] = []

    def measure(
        run_id: str, snapshot: dict[str, str], method: str, repeat: int,
        agent_variant: str, recorded_from: str | None,
    ) -> dict[str, object]:
        observed.append((snapshot["path"], method, repeat))
        return dict.fromkeys(bench.ACCURACY, 0.5)

    monkeypatch.setattr(bench, "_measure", measure)
    args = argparse.Namespace(
        methods=["agent_no_prior", "react", "agent"], run_id="live", repeats=2,
        scenario_dir=[], split="development", output_dir=tmp_path, change="Test",
    )
    assert bench.run(args)
    assert observed == [
        (str(snapshot["path"]), method, repeat) for snapshot in snapshots for repeat in range(2)
        for method in ("agent", "react", "agent_no_prior")
    ]
