"""Render showcase/poster.png (1280x720) from results/summary.json: agent vs baselines,
top-1 and top-3 per scenario. Deterministic: no randomness, fixed fonts and sizes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
METHODS = [("agent", "LLM agent", "#2563eb"), ("composite_zscore", "Composite z-score", "#f59e0b"),
           ("zscore", "Error-rate z-score", "#10b981"), ("random", "Random", "#9ca3af")]


def main(summary_path: Path, out: Path) -> None:
    s = json.loads(summary_path.read_text())
    scen = list(s["per_scenario"].items())
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.hashsalt": "otel"})
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100, facecolor="white")
    fig.text(0.04, 0.93,
             "otel-sre-copilot — LLM agent vs. anomaly baselines on Kubernetes incidents",
             fontsize=19, weight="bold")
    fig.text(0.04, 0.885, "Exact root cause (service + fault type) per Chaos Mesh scenario, "
             "solid = top-1, light = top-3", fontsize=12.5, color="#374151")

    ax = fig.add_axes((0.06, 0.25, 0.66, 0.58))
    n_m = len(METHODS)
    width = 0.8 / n_m
    for j, (key, _label, color) in enumerate(METHODS):
        for i, (_name, data) in enumerate(scen):
            d = data.get(key)
            if not d:
                continue
            x = i + (j - (n_m - 1) / 2) * width
            ax.bar(x, d["accuracy_at_3"] or 0, width * 0.92, color=color, alpha=0.3)
            ax.bar(x, d["accuracy_at_1"] or 0, width * 0.92, color=color)
    labels = [f"{d['ground_truth']['service']}\n{d['ground_truth']['fault_type']}"
              for _n, d in scen]
    ax.set_xticks(range(len(scen)), labels, fontsize=9)
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    ax.legend(handles=[Patch(color=c, label=lab) for _k, lab, c in METHODS], ncol=4,
              loc="upper center", bbox_to_anchor=(0.5, -0.17), frameon=False, fontsize=11)

    # Headline numbers
    y = 0.80
    fig.text(0.76, y, "All snapshots", fontsize=14, weight="bold")
    y -= 0.055
    fig.text(0.805, y, "top-1", fontsize=11, color="#6b7280")
    fig.text(0.895, y, "top-3", fontsize=11, color="#6b7280")
    for key, label, color in METHODS:
        m = s["methods"].get(key)
        if not m:
            continue
        y -= 0.06
        fig.text(0.76, y, label, fontsize=11.5, color=color, weight="bold")
        std = m.get("accuracy_at_1_std_across_repeats")
        top1 = f"{m['accuracy_at_1'] * 100:.0f}%" + (f"±{std * 100:.0f}" if std else "")
        fig.text(0.805, y - 0.032, top1, fontsize=11.5)
        fig.text(0.895, y - 0.032, f"{m['accuracy_at_3'] * 100:.0f}%", fontsize=11.5)
        y -= 0.03
    agent = s["methods"].get("agent")
    if agent:
        y -= 0.07
        fig.text(0.76, y, f"Agent grounding  {agent['grounding_score']:.2f}", fontsize=11.5)
        y -= 0.04
        fig.text(0.76, y, f"Latency  {agent['latency_s']:.0f} s / incident", fontsize=11.5)
        y -= 0.04
        fig.text(0.76, y, f"Tokens  {agent['tokens_per_investigation'] / 1000:.0f}k / incident",
                 fontsize=11.5)

    setup = s.get("setup", "")
    fig.text(0.04, 0.035, _wrap(setup, 170), fontsize=9, color="#6b7280", va="bottom")
    fig.savefig(out, dpi=100, facecolor="white", metadata={"Software": None})


def _wrap(text: str, n: int) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return "\n".join([*lines, cur])


if __name__ == "__main__":
    summary = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results" / "summary.json"
    main(summary, ROOT / "showcase" / "poster.png")
