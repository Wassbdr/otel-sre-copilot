from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from eval.bench import LABELS, _format, summarize_rows
from eval.scenario_runner import write_json_atomic

COHORTS = {
    "Held-out": "round2-held-out",
    "New development": "round2-new-development",
    "Tuned development": "round2-reference-aligned",
}
METHODS = ("agent", "nsigma", "composite_zscore", "baro", "holmes",
           "react", "agent_no_prior", "zscore", "random")
START = "<!-- final-comparison:start -->"
END = "<!-- final-comparison:end -->"


def summarize(history: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {run["run_id"]: run for run in history}
    cohorts: dict[str, Any] = {}
    pooled: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    setup: dict[str, Any] | None = None
    for label, run_id in COHORTS.items():
        run = by_id.get(run_id)
        if run is None:
            raise ValueError(f"Missing benchmark cohort: {run_id}")
        current = {key: run["setup"][key] for key in ("model", "hardware", "repeats")}
        if setup is not None and current != setup:
            raise ValueError(f"Benchmark setup differs for {run_id}")
        setup = current
        snapshots = {s["scenario_id"]: s["sha256"] for s in run["setup"]["snapshots"]}
        if not snapshots or seen.intersection(snapshots):
            raise ValueError(f"Empty or overlapping benchmark cohort: {run_id}")
        seen.update(snapshots)
        methods = {}
        misses: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for method in METHODS:
            repeats = 1 if method == "holmes" else setup["repeats"]
            expected = {(sid, repeat) for sid in snapshots for repeat in range(repeats)}
            rows = run["rows"].get(method, [])
            actual = {(row["scenario_id"], row["repeat"]) for row in rows
                      if "error" not in row and snapshots.get(row["scenario_id"]) == row["sha256"]}
            if actual != expected or len(rows) != len(expected):
                raise ValueError(f"Incomplete or mismatched benchmark rows: {run_id}/{method}")
            methods[method] = summarize_rows(rows, repeats, len(snapshots))
            pooled[method].extend(rows)
            if method == "agent":
                for row in rows:
                    counts = misses[row["scenario_id"].rsplit("-seed", 1)[0]]
                    counts[0] += row["accuracy_at_1"] < 1
                    counts[1] += row["accuracy_at_3"] < 1
                    counts[2] += 1
        cohorts[label] = {"snapshots": len(snapshots), "methods": methods,
                          "misses": {k: v for k, v in misses.items() if v[0] or v[1]}}
    assert setup is not None
    cohorts["Pooled"] = {
        "snapshots": len(seen),
        "methods": {
            method: summarize_rows(rows, 1 if method == "holmes" else setup["repeats"], len(seen))
            for method, rows in pooled.items()
        },
    }
    return {**setup, "cohorts": cohorts}


def agent_by_cohort(summary: dict[str, Any]) -> str:
    lines = [
        "| Cohort | Runs | Service top-1 | Service top-3 | Grounded citations | "
        "Tokens/run | Seconds/run | USD/run |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label, cohort in summary["cohorts"].items():
        row = cohort["methods"]["agent"]
        cells = [label, str(row["completed"]), _format(row["service_at_1"], ".1%"),
                 _format(row["service_at_3"], ".1%"),
                 f"{row['verified_evidence_count']}/{row['evidence_count']}",
                 _format(row["total_tokens"], ",.0f"), _format(row["latency_s"], ".2f"),
                 _format(row["cost_usd"], ".4f")]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def comparison(summary: dict[str, Any]) -> str:
    cohorts = summary["cohorts"]
    held, new, tuned, pooled = (cohorts[key] for key in (*COHORTS, "Pooled"))

    def accuracy(m: dict[str, Any]) -> str:
        return " / ".join(_format(m[key], ".1%") for key in ("accuracy_at_1", "accuracy_at_3"))

    def runtime(m: dict[str, Any]) -> str:
        return " | ".join(_format(m[key], spec) for key, spec in (
            ("grounding_score", ".1%"), ("total_tokens", ",.0f"),
            ("latency_s", ".2f"), ("cost_usd", ".4f"),
        ))

    lines = [
        f"Astronomy Shop replay: {held['snapshots']} held-out, {new['snapshots']} new untuned "
        f"development, {tuned['snapshots']} tuned development snapshots; "
        f"`{summary['model']}` via NVIDIA NIM; {summary['repeats']} runs per Copilot method "
        f"and 1 per HolmesGPT snapshot; {summary['hardware']}.",
        "",
        "Each accuracy cell is strict top-1 / top-3 (service and fault type). Multi-fault "
        "runs score the fraction of true causes covered. Grounding and per-run costs are pooled.",
        "",
        "| Method | Held-out | New development | Tuned development | Pooled | "
        "Grounding | Tokens | Seconds | USD |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    ranking = sorted(METHODS, key=lambda method: tuple(
        -cohort["methods"][method][metric]
        for cohort in (held, new, tuned)
        for metric in ("accuracy_at_1", "accuracy_at_3")
    ))
    for method in ranking:
        scores = " | ".join(accuracy(cohort["methods"][method]) for cohort in cohorts.values())
        label = LABELS[method] if method != "agent" else "**SRE-Copilot**"
        lines.append(f"| {label} | {scores} | {runtime(pooled['methods'][method])} |")
    for label, cohort in cohorts.items():
        methods = cohort["methods"]
        ref = max((method for method in METHODS if method != "agent"),
                  key=lambda method: methods[method]["service_at_3"])
        reference = methods[ref]["service_at_3"]
        agent = methods["agent"]["service_at_3"]
        if reference > agent:
            lines.extend([
                "",
                f"{LABELS[ref]} leads on service-only top-3 for {label.lower()} "
                f"({reference:.1%} vs. {agent:.1%}); the table uses strict matching.",
            ])
    lines.extend([
        "",
        "Seconds exclude rate-limit waits. USD reflects NIM free-tier pricing. "
        "Grounding is the share of citations matched to tool calls; n/a means no citations.",
    ])
    return "\n".join(lines)


def miss_list(summary: dict[str, Any]) -> str:
    lines = [
        "Runs missing any true cause, grouped by scenario across seeds (top-1 / top-3). "
        "For two-fault incidents, top-1 necessarily misses at least one cause.",
        "",
    ]
    for label in COHORTS:
        misses = summary["cohorts"][label]["misses"]
        details = "; ".join(
            f"`{scenario}` {top1}/{runs} / {top3}/{runs}"
            for scenario, (top1, top3, runs) in sorted(misses.items())
        )
        lines.append(f"- **{label}:** {details or 'none'}.")
    return "\n".join(lines)


def write_section(path: Path, body: str, *, insert: bool = False) -> None:
    content = path.read_text()
    if START in content and END in content:
        head, rest = content.split(START, 1)
        _, tail = rest.split(END, 1)
    elif insert:
        title, _, rest = content.partition("\n\n")
        head, tail = f"{title}\n\n", f"\n\n{rest}"
    else:
        raise ValueError(f"Missing final comparison markers in {path}")
    path.write_text(f"{head}{START}\n{body}\n{END}{tail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the completed recorded comparison.")
    parser.add_argument("--summary", type=Path, default=Path("results/final-summary.json"))
    args = parser.parse_args()
    summary = summarize(json.loads(Path("benchmarks/results.json").read_text()))
    table = comparison(summary)
    write_section(Path("README.md"), table)
    write_section(
        Path("benchmarks/results.md"),
        f"## Final comparison\n\n{table}\n\n### SRE-Copilot by cohort\n\n"
        f"{agent_by_cohort(summary)}\n\n### SRE-Copilot misses\n\n{miss_list(summary)}",
        insert=True,
    )
    write_json_atomic(args.summary, summary)


if __name__ == "__main__":
    main()
