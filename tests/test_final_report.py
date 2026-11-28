from pathlib import Path
from typing import Any

import pytest

from eval.final_report import COHORTS, METHODS, comparison, miss_list, summarize, write_section


def cohort(run_id: str, size: int) -> dict[str, Any]:
    snapshots = [{"scenario_id": f"{run_id}-seed{i}", "sha256": str(i)} for i in range(size)]
    return {
        "run_id": run_id,
        "setup": {"model": "test", "hardware": "CPU", "repeats": 3, "snapshots": snapshots},
        "rows": {
            method: [
                {**snapshot, "repeat": repeat, "accuracy_at_1": float(size == 1),
                 "accuracy_at_3": 0.5, "service_at_1": 0.5, "service_at_3": 0.5,
                 "evidence_count": 2, "verified_evidence_count": 1}
                for snapshot in snapshots for repeat in range(1 if method == "holmes" else 3)
            ]
            for method in METHODS
        },
    }


def test_final_report_pools_runs_and_preserves_separate_cohorts(tmp_path: Path) -> None:
    history = [cohort(run_id, i) for i, run_id in enumerate(COHORTS.values(), 1)]
    result = summarize(history)
    pooled = result["cohorts"]["Pooled"]["methods"]
    assert pooled["agent"]["completed"] == 18
    assert pooled["holmes"]["completed"] == 6
    assert pooled["agent"]["accuracy_at_1"] == pytest.approx(1 / 6)
    assert pooled["agent"]["grounding_score"] == 0.5
    assert "100.0% / 50.0%" in comparison(result)
    assert "`round2-held-out` 0/3 / 3/3" in miss_list(result)
    path = tmp_path / "results.md"
    path.write_text("# Title\n\nPrevious results\n")
    write_section(path, "comparison", insert=True)
    write_section(path, "revised comparison", insert=True)
    assert path.read_text().count("comparison:start") == 1
    assert path.read_text().endswith("<!-- final-comparison:end -->\n\nPrevious results\n")
    history[0]["rows"]["agent"].pop()
    with pytest.raises(ValueError, match="Incomplete or mismatched benchmark rows"):
        summarize(history)
