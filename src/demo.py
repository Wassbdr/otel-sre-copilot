"""Terminal demo: watch the agent investigate one incident.

    sre-copilot-demo                       # offline: replays the recorded checkout pod-crash trace
    sre-copilot-demo --trace <trace.json>  # any trace.json written by eval.scenario_runner
    sre-copilot-demo --live --snapshot-dir snapshots/checkout-pod_crash-seed42
                                           # live LLM (needs LLM_API_KEY or NIM_API_KEY) on the
                                           # recorded telemetry of a snapshot

Replay mode makes no network call: it re-renders the tool calls, the report and the external
grounding check exactly as they were recorded, and says so on screen.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

DEFAULT_TRACE = (
    Path(__file__).resolve().parent.parent / "examples" / "checkout-pod-crash.trace.json"
)

_TOOL_ARG_KEYS = ("query", "logql", "service_name", "trace_id", "pod_name", "namespace")


def _short(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _args_summary(args: dict[str, Any]) -> str:
    keys = [k for k in _TOOL_ARG_KEYS if k in args] or list(args)[:2]
    parts = [f"{k}={_short(str(args[k]), 70)}" for k in keys]
    if args.get("error_only"):
        parts.append("error_only=True")
    return ", ".join(parts)


class Renderer:
    def __init__(self, console: Console, delay: float) -> None:
        self.c = console
        self.delay = delay
        self.step = 0

    def pause(self, factor: float = 1.0) -> None:
        if self.delay:
            time.sleep(self.delay * factor)

    def header(self, title: str, subtitle: str, window: dict[str, Any], mode_note: str) -> None:
        body = Text()
        body.append(f"{title}\n", style="bold")
        body.append(f"window {window.get('start', '?')[:19]} → {window.get('end', '?')[:19]} UTC"
                    f"   namespace {window.get('namespace', 'otel-demo')}\n", style="dim")
        body.append(mode_note, style="yellow")
        self.c.print(Panel(body, title="otel-sre-copilot", subtitle=subtitle, expand=True))
        self.pause(2)

    def tool_call(self, call: dict[str, Any]) -> None:
        self.step += 1
        name = str(call.get("tool_name"))
        head = Text(f" {self.step:>2} ▸ ", style="bold cyan")
        head.append(name, style="bold")
        head.append(f"({_args_summary(call.get('args', {}))})", style="cyan")
        self.c.print(head, no_wrap=True, overflow="ellipsis")
        excerpt = str(call.get("result_excerpt") or call.get("result_preview") or "")
        lines = [ln for ln in excerpt.splitlines() if ln.strip()][:3]
        for ln in lines:
            self.c.print(Text("      " + _short(ln, 110), style="dim"), no_wrap=True,
                         overflow="ellipsis")
        self.pause(1.2)

    def report(self, report: dict[str, Any], grounding: dict[str, Any] | None,
               ground_truth: dict[str, Any] | None) -> None:
        causes = report.get("root_causes") or []
        table = Table(title="Ranked root causes", expand=True, title_style="bold")
        table.add_column("#", width=2)
        table.add_column("service", style="bold")
        table.add_column("fault type")
        table.add_column("conf.", justify="right")
        table.add_column("why", ratio=1)
        for rc in causes:
            table.add_row(str(rc.get("rank")), str(rc.get("service")), str(rc.get("fault_type")),
                          f"{float(rc.get('confidence', 0)):.2f}",
                          _short(str(rc.get("description", "")), 90))
        self.c.print()
        self.c.print(table)
        self.pause(2)

        failed = {(str(f.get("rank")), str(f.get("query_or_id"))) for f in
                  (grounding or {}).get("failed_items", [])}
        ev = Table(title="Cited evidence  ·  external grounding check against the tool-call log",
                   expand=True, title_style="bold")
        ev.add_column("#", width=2)
        ev.add_column("type", width=9)
        ev.add_column("cited query / span / log", ratio=3)
        ev.add_column("observed", ratio=2)
        ev.add_column("", width=11)
        for rc in causes:
            for item in rc.get("evidence", []):
                ok = (str(rc.get("rank")), str(item.get("query_or_id"))) not in failed
                ev.add_row(str(rc.get("rank")), str(item.get("signal_type")),
                           _short(str(item.get("query_or_id")), 80),
                           _short(str(item.get("observed_value", "")), 50),
                           Text("✔ verified", style="green") if ok
                           else Text("✘ not found", style="red"))
        self.c.print(ev)
        self.pause(2)

        if grounding is not None:
            score = float(grounding.get("score", 0.0))
            style = "bold green" if score >= 0.8 else "bold red"
            verdict = "grounded" if score >= 0.8 else "[HALLUCINATION WARNING]"
            line = Text("Grounding ", style="bold")
            line.append(f"{score:.2f}", style=style)
            line.append(f"  ({grounding.get('verified')}/{grounding.get('total')} evidence items "
                        f"match a real tool call) — {verdict}")
            self.c.print(line)
        steps = report.get("remediation_steps") or []
        if steps:
            self.c.print(Text("Remediation: ", style="bold") + Text(_short(steps[0], 120)))
        if ground_truth:
            top = causes[0] if causes else {}
            hit = top.get("service") == ground_truth.get("fault_service")
            truth = Text("Chaos Mesh ground truth: ", style="bold")
            truth.append(
                f"{ground_truth.get('fault_service')} / {ground_truth.get('fault_type')}  "
            )
            truth.append("→ top-1 correct" if hit else "→ top-1 wrong",
                         style="bold green" if hit else "bold red")
            self.c.print(truth)
        self.pause(3)


def replay(trace_path: Path, delay: float, console: Console) -> int:
    trace = json.loads(trace_path.read_text())
    r = Renderer(console, delay)
    r.header(
        f"Incident {trace.get('scenario_id')}",
        f"model {trace.get('model')}",
        trace.get("window", {}),
        "REPLAY of a recorded agent run — no LLM or network call is made.",
    )
    for call in trace.get("tool_calls", []):
        r.tool_call(call)
    report = trace.get("report", {})
    lat = report.get("latency_s")
    tokens = (report.get("total_prompt_tokens") or 0) + (report.get("total_completion_tokens") or 0)
    console.print(Text(f"\n  recorded run: {len(trace.get('tool_calls', []))} tool calls, "
                       f"{lat:.1f} s, {tokens:,} tokens" if lat else "", style="dim"))
    r.report(report, trace.get("grounding"), trace.get("ground_truth"))
    return 0


def live(snapshot_dir: Path, console: Console) -> int:
    from eval.grounding_verifier import verify
    from eval.scenario_runner import opaque_incident_id
    from src.agent.graph import build_graph
    from src.agent.llm import llm_settings
    from src.agent.schemas import initial_state
    from src.datasources.replay import ReplayDataSource

    settings = llm_settings()
    if not settings.is_fake and not settings.api_key:
        console.print("[red]--live needs an API key:[/] export LLM_API_KEY=… (any "
                      "OpenAI-compatible endpoint) or NIM_API_KEY=… (NVIDIA NIM, free tier).")
        return 2
    meta = json.loads((snapshot_dir / "metadata.json").read_text())
    gt = json.loads((snapshot_dir / "ground_truth.json").read_text())
    window = {"start": meta["window_start"], "end": meta["window_end"],
              "namespace": meta.get("namespace", "otel-demo")}
    r = Renderer(console, delay=0)
    r.header(f"Incident {gt.get('scenario_id', snapshot_dir.name)}", f"model {settings.model}",
             window, f"LIVE LLM run on the recorded telemetry of {snapshot_dir}")

    def on_event(event: dict[str, Any]) -> None:
        if event["type"] == "tool_call":
            r.tool_call(event)
        elif event["type"] == "llm":
            console.print(Text(f"    · LLM step {event['iteration']} "
                               f"({event['elapsed_s']} s, {event['n_tool_calls']} tool calls)",
                               style="dim"))

    graph = build_graph(ReplayDataSource(snapshot_dir), on_event=on_event)
    state = initial_state(opaque_incident_id(str(gt.get("scenario_id"))), window["start"],
                          window["end"],
                          window["namespace"])
    state["_investigation_start_ts"] = datetime.now(UTC).isoformat()
    with console.status("investigating…"):
        result = graph.invoke(state, {"recursion_limit": 100})
    report = result["final_report"]
    g = verify(report, result.get("tool_calls_log", []))
    r.report(report.model_dump(mode="json"),
             {"score": g.grounding_score, "verified": g.verified_count, "total": g.total_count,
              "failed_items": g.failed_items}, gt)
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE,
                        help="Recorded trace.json to replay (default: checkout pod crash)")
    parser.add_argument("--live", action="store_true", help="Run the LLM live (needs a key)")
    parser.add_argument("--snapshot-dir", type=Path,
                        default=Path("snapshots/checkout-pod_crash-seed42"))
    parser.add_argument("--speed", type=float, default=1.0,
                        help="Replay pacing multiplier (0 = no pauses)")
    args = parser.parse_args(argv)
    console = Console(width=min(Console().width, 130), highlight=False)
    if args.live:
        sys.exit(live(args.snapshot_dir, console))
    delay = 0.0 if args.speed == 0 else 0.5 / args.speed
    sys.exit(replay(args.trace, delay, console))


if __name__ == "__main__":
    main()
