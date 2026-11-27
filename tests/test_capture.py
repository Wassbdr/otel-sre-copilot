from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import inject_and_snapshot as capture


def test_multifault_capture_records_all_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(capture, "_SNAPSHOTS_DIR", tmp_path)
    scenario = Path("scenarios/extended/012-currency-cpu-cart-loss.yaml")
    capture.inject(scenario, dry_run=True, seed=23)
    truth = json.loads((tmp_path / "currency-cart-multi-seed23/ground_truth.json").read_text())

    assert truth["seed"] == 23
    assert truth["split"] == "held-out"
    assert "fault_service" not in truth
    assert {(f["fault_service"], f["fault_type"]) for f in truth["faults"]} == {
        ("currency", "cpu_stress"),
        ("cart", "http_abort"),
    }


def test_single_fault_retains_existing_ground_truth_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(capture, "_SNAPSHOTS_DIR", tmp_path)
    capture.inject(Path("scenarios/mvp/001-checkoutservice-pod-crash.yaml"), dry_run=True, seed=23)
    truth = json.loads((tmp_path / "checkout-pod_crash-seed23/ground_truth.json").read_text())
    assert (truth["fault_service"], truth["fault_type"], truth["seed"]) == (
        "checkout", "pod_crash", 23,
    )
    assert "faults" not in truth
