from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1%}"


def main(summary_path: Path) -> None:
    output_path = ROOT / "showcase" / "showcase.json"
    previous = json.loads(output_path.read_text()) if output_path.exists() else {}
    s = json.loads(summary_path.read_text())
    bench = "python -m eval.final_report"
    setup = (
        f"{s['model']} via NVIDIA NIM; {s['repeats']} runs per Copilot method "
        f"and 1 per HolmesGPT snapshot; {s['hardware']}."
    )
    results = []
    cohorts = s["cohorts"]
    for label, cohort in cohorts.items():
        agent = cohort["methods"]["agent"]
        results.append({
            "label": f"{label} agent strict top-1 / top-3",
            "value": f"{pct(agent['accuracy_at_1'])} / {pct(agent['accuracy_at_3'])}",
            "command": bench, "setup": f"{cohort['snapshots']} snapshots; {setup}",
        })
    agent = cohorts["Pooled"]["methods"]["agent"]
    results += [
        {"label": "Pooled grounded citations", "value": pct(agent["grounding_score"]),
         "command": bench, "setup": setup},
        {"label": "Pooled agent latency / tokens / cost per investigation",
         "value": f"{agent['latency_s']:.1f} s / {agent['total_tokens']:,.0f} tokens "
                  f"/ ${agent['cost_usd']:.4f}",
         "command": bench, "setup": f"{setup} Excludes rate-limit waits."},
    ]
    doc = {
        "slug": "otel-sre-copilot",
        "title": "OTel SRE-Copilot",
        "tagline": "An LLM agent that investigates Kubernetes incidents from OpenTelemetry "
                   "metrics, traces and logs, with citations checked against tool calls.",
        "problem": "During an incident an on-call engineer has to correlate dashboards, traces, "
                   "logs and Kubernetes events across a dozen services before finding the one "
                   "that broke. LLM agents promise to automate this, but they are rarely "
                   "measured against simple anomaly-detection baselines and they can invent "
                   "evidence.",
        "approach": "Telemetry fingerprints rank service and fault pairs. A LangGraph agent "
                    "can reorder those candidates using Prometheus, Tempo, Loki and Kubernetes "
                    "events. Unsupported diagnoses are removed; remaining slots use the "
                    "grounded prior. The benchmark uses recorded Astronomy Shop telemetry.",
        "stack": ["Python", "LangGraph", "LangChain", "NVIDIA NIM (OpenAI-compatible)",
                  "OpenTelemetry", "Prometheus", "Grafana Tempo", "Grafana Loki", "Kubernetes",
                  "kind", "Helm", "Chaos Mesh", "Pydantic", "Rich"],
        "demo": {"gif": "showcase/demo.gif", "mp4": "showcase/demo.mp4",
                 "poster": "showcase/poster.png", "kind": "replay",
                 "caption": "Replay of a recorded agent run on the checkout pod-crash incident: "
                            "the tool calls, ranked root "
                            "causes, the cited evidence with the grounding verifier's verdict, "
                            "and the Chaos Mesh ground truth."},
        "reproduce": ["git clone https://github.com/Wassbdr/otel-sre-copilot",
                      "cd otel-sre-copilot",
                      "pip install -e .", "make demo",
                      "python -m eval.final_report"],
        "results": results,
        "limits": [
            "One demo application and one model. The original development cohort was used "
            "for tuning; new development and held-out results are reported separately.",
            "Replay answers recorded queries and includes only sampled traces.",
            "HolmesGPT ran once per snapshot. k8sgpt and OpenRCA could not run on matched inputs.",
        ],
        "role": previous.get("role", "Sole developer."),
        "repo": "https://github.com/Wassbdr/otel-sre-copilot",
    }
    output_path.write_text(json.dumps(doc, indent=2) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results" / "final-summary.json")
