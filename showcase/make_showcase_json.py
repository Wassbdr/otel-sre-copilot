"""Write showcase/showcase.json from results/summary.json (numbers are never typed by hand)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def main(summary_path: Path) -> None:
    output_path = ROOT / "showcase" / "showcase.json"
    previous = json.loads(output_path.read_text()) if output_path.exists() else {}
    s = json.loads(summary_path.read_text())
    m = s["methods"]
    run_id = s["run_id"]
    bench = f"python -m eval.report --run-id {run_id}  (re-measure: make benchmark)"
    setup = s["setup"]
    agent = m.get("agent", {})
    results = []
    if agent:
        std1 = agent.get("accuracy_at_1_std_across_repeats")
        results += [
            {"label": "Agent top-1 root-cause accuracy (service + fault type)",
             "value": pct(agent["accuracy_at_1"]) + (f" ± {std1 * 100:.0f} pts" if std1 else ""),
             "command": bench, "setup": setup},
            {"label": "Agent top-3 root-cause accuracy (service + fault type)",
             "value": pct(agent["accuracy_at_3"]), "command": bench, "setup": setup},
            {"label": "Agent faulty-service top-1 / top-3 (composite z-score: "
                      f"{pct(m['composite_zscore']['service_at_1'])} / "
                      f"{pct(m['composite_zscore']['service_at_3'])})"
                      if "composite_zscore" in m else "Agent faulty-service top-1 / top-3",
             "value": f"{pct(agent['service_at_1'])} / {pct(agent['service_at_3'])}",
             "command": bench, "setup": setup},
            {"label": "Agent grounding score (cited evidence matched to real tool calls)",
             "value": f"{agent['grounding_score']:.2f}", "command": bench, "setup": setup},
            {"label": "Agent latency / tokens per investigation",
             "value": f"{agent['latency_s']:.1f} s / "
                      f"{agent['tokens_per_investigation']:,.0f} tokens",
             "command": bench, "setup": setup},
        ]
    for key, label in (("composite_zscore", "Composite z-score baseline"),
                       ("zscore", "Error-rate z-score baseline"), ("random", "Random baseline")):
        if key in m:
            results.append({"label": f"{label} top-1 / top-3",
                            "value": f"{pct(m[key]['accuracy_at_1'])} / "
                                     f"{pct(m[key]['accuracy_at_3'])}",
                            "command": "python -m eval.scenario_runner --mode baselines-only",
                            "setup": setup})
    doc = {
        "slug": "otel-sre-copilot",
        "title": "OTel SRE-Copilot",
        "tagline": "An LLM agent that investigates Kubernetes incidents from OpenTelemetry "
                   "metrics, traces and logs, and proves every piece of evidence it cites.",
        "problem": "During an incident an on-call engineer has to correlate dashboards, traces, "
                   "logs and Kubernetes events across a dozen services before finding the one "
                   "that broke. LLM agents promise to automate this, but they are rarely "
                   "measured against simple anomaly-detection baselines and they can invent "
                   "evidence.",
        "approach": "A LangGraph tool-calling agent queries Prometheus, Tempo, Loki and "
                    "Kubernetes events through one DataSource interface, under a token budget, "
                    "and returns ranked root causes with cited evidence. An external verifier "
                    "checks each citation against the tool calls really made. Faults are "
                    "injected with Chaos Mesh on the OpenTelemetry Astronomy Shop, recorded as "
                    "replayable snapshots, and scored against random and z-score baselines.",
        "stack": ["Python", "LangGraph", "LangChain", "NVIDIA NIM (OpenAI-compatible)",
                  "OpenTelemetry", "Prometheus", "Grafana Tempo", "Grafana Loki", "Kubernetes",
                  "kind", "Helm", "Chaos Mesh", "Pydantic", "Rich"],
        "demo": {"gif": "showcase/demo.gif", "mp4": "showcase/demo.mp4",
                 "poster": "showcase/poster.png", "kind": "replay",
                 "caption": "Replay of a recorded agent run on the checkout pod-crash incident: "
                            "each Prometheus/Tempo/Loki/Kubernetes tool call, the ranked root "
                            "causes, the cited evidence with the grounding verifier's verdict, "
                            "and the Chaos Mesh ground truth."},
        "reproduce": ["git clone https://github.com/Wassbdr/otel-sre-copilot",
                      "cd otel-sre-copilot",
                      "pip install -e .", "make demo",
                      "NIM_API_KEY=... make benchmark"],
        "results": results,
        "limits": [
            f"{s['n_snapshots']} snapshots of {s['n_scenarios']} single-fault scenarios on one "
            "demo app: too small to generalise, and seeds only change the capture time.",
            "Snapshots are replayed, so the agent cannot run queries outside the captured set "
            "(unknown PromQL falls back to the closest recorded series).",
            "LLM runs are not bit-reproducible even at temperature 0; variance is reported over "
            "3 runs per snapshot.",
            "Single model measured (NIM free tier); no multi-fault or cascading incidents.",
        ],
        "role": previous.get("role", "Sole developer."),
        "repo": "https://github.com/Wassbdr/otel-sre-copilot",
    }
    output_path.write_text(json.dumps(doc, indent=2) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results" / "summary.json")
