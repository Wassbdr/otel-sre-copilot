"""eval.report aggregation: agent repeats, per-scenario tables, variance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eval.report import headline_table, scenario_table, summarize


def _run(top1: str, a1: float, a3: float, repeat: int = 0, tokens: int = 0) -> dict[str, Any]:
    return {"predicted_service_top1": top1, "accuracy_at_1": a1, "accuracy_at_3": a3, "mrr": a1,
            "fault_type_correct": 0.0, "grounding_score": 1.0, "latency_s": 2.0,
            "total_tokens": tokens, "repeat": repeat, "ground_truth_service": "checkout",
            "ground_truth_fault_type": "pod_crash", "hallucination_warning": False}


RAW = [
    {"snapshot_dir": "s/a", "scenario_id": "checkout-pod_crash-seed42",
     "scenario": "checkout-pod_crash", "seed": 42,
     "random": _run("cart", 0, 0), "zscore": _run("checkout", 1, 1),
     "agent_runs": [_run("checkout", 1, 1, 0, 100), _run("cart", 0, 1, 1, 300),
                    {"repeat": 2, "error": "timeout"}]},
    {"snapshot_dir": "s/b", "scenario_id": "checkout-pod_crash-seed7",
     "scenario": "checkout-pod_crash", "seed": 7,
     "random": _run("ad", 0, 1), "zscore": _run("checkout", 1, 1),
     "agent_runs": [_run("checkout", 1, 1, 0, 100), _run("checkout", 1, 1, 1, 100)]},
    {"snapshot_dir": "s/c", "error": "boom"},
]


def test_summary_averages_every_successful_agent_run() -> None:
    s = summarize(RAW)
    agent = s["methods"]["agent"]
    assert s["n_snapshots"] == 2 and s["failed_snapshots"] == ["s/c"]
    assert agent["n"] == 4
    assert agent["accuracy_at_1"] == 0.75
    assert agent["tokens_per_investigation"] == 150
    # repeat 0: 2/2 correct, repeat 1: 1/2 correct → per-pass spread
    assert agent["accuracy_at_1_per_repeat"] == [1.0, 0.5]
    assert agent["accuracy_at_1_std_across_repeats"] == 0.25


def test_per_scenario_groups_seeds() -> None:
    s = summarize(RAW)
    sc = s["per_scenario"]["checkout-pod_crash"]
    assert sc["seeds"] == [7, 42]
    assert sc["zscore"]["accuracy_at_1"] == 1.0
    assert sc["random"]["accuracy_at_3"] == 0.5


def test_tables_render() -> None:
    s = summarize(RAW)
    assert "75% ± 25" in headline_table(s)
    assert "`checkout-pod_crash` (checkout, pod_crash)" in scenario_table(s)


def test_update_readme_rewrites_only_the_marked_block(tmp_path: Path) -> None:
    from eval.report import README_END, README_START, update_readme

    readme = tmp_path / "README.md"
    readme.write_text(f"intro\n{README_START}\nold\n{README_END}\noutro\n")
    summary = {"methods": {"random": {"accuracy_at_1": 0.1, "accuracy_at_3": 0.2,
                                      "grounding_score": None, "latency_s": 0.0,
                                      "tokens_per_investigation": 0}},
               "setup": "setup.", "run_id": "r1"}
    assert update_readme(summary, readme)
    text = readme.read_text()
    assert text.startswith("intro\n") and text.endswith("outro\n")
    assert "old" not in text and "| Random | 10% | 20% |" in text
