from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
METHODS = [("agent", "SRE-Copilot", "#0f766e"), ("nsigma", "N-Sigma", "#2563eb"),
           ("composite_zscore", "Composite z-score", "#92400e"), ("holmes", "HolmesGPT", "#7e22ce"),
           ("react", "ReAct", "#475569")]


def main(summary: Path, output: Path) -> None:
    data = json.loads(summary.read_text())
    cohorts = data["cohorts"]
    held = cohorts["Held-out"]["methods"]["agent"]
    plt.rcParams.update({"font.family": "DejaVu Sans"})
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100, facecolor="#f8fafc")
    fig.text(0.05, 0.91, "OTel SRE-Copilot", color="#0f172a", weight="bold", fontsize=34)
    fig.text(0.05, 0.857, "Root cause on replayed Kubernetes incidents", color="#334155",
             fontsize=16)
    axis = fig.add_axes((0.095, 0.27, 0.60, 0.49), facecolor="#f8fafc")
    width = 0.15
    for j, (method, _label, color) in enumerate(METHODS):
        for i, cohort in enumerate(cohorts.values()):
            result = cohort["methods"][method]
            x = i + (j - 2) * width
            axis.bar(x, result["accuracy_at_3"], width * 0.9, color=color, alpha=0.25)
            axis.bar(x, result["accuracy_at_1"], width * 0.9, color=color)
    axis.set_xticks(
        range(len(cohorts)),
        [f"{label.replace(' development', ' dev')}\n{d['snapshots']} snapshots"
         for label, d in cohorts.items()],
    )
    axis.set_ylim(0, 1.06)
    axis.set_yticks([0, 0.25, 0.5, 0.75, 1], ["0%", "25%", "50%", "75%", "100%"])
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.tick_params(length=0, pad=8)
    axis.grid(axis="y", color="#dbe3ec")
    axis.set_axisbelow(True)
    axis.legend(handles=[Patch(color=color, label=label) for _, label, color in METHODS],
                ncol=len(METHODS), loc="upper center", bbox_to_anchor=(0.5, -0.18),
                frameon=False, fontsize=10)

    fig.text(0.75, 0.735, "Held-out agent", weight="bold", color="#334155", fontsize=15)
    fig.text(0.75, 0.62, f"{held['accuracy_at_3']:.1%}", weight="bold",
             color="#0f766e", fontsize=39)
    fig.text(0.75, 0.575, "strict top-3", fontsize=15, color="#334155")
    fig.text(0.75, 0.485, f"{held['accuracy_at_1']:.1%} strict top-1", fontsize=14, color="#0f172a")
    fig.text(0.75, 0.43, f"{held['grounding_score']:.1%} grounded citations",
             fontsize=14, color="#0f172a")
    fig.text(0.75, 0.36, f"{held['latency_s']:.1f} s / run", fontsize=13, color="#334155")
    fig.text(0.75, 0.315, f"{held['total_tokens']:,.0f} tokens / run",
             fontsize=13, color="#334155")
    fig.text(0.05, 0.103, "Strict match = service and fault type. Solid = top-1; light = top-3.",
             fontsize=11, color="#334155")
    fig.text(0.05, 0.05,
             f"{data['model']} via NIM • {data['repeats']} repeats "
             f"(HolmesGPT: 1) • {data['hardware']} • Rate-limit waits excluded",
             fontsize=9.5, color="#475569")
    fig.savefig(output, dpi=100, metadata={"Software": None})


if __name__ == "__main__":
    main(Path(sys.argv[1]), ROOT / "showcase" / "poster.png")
