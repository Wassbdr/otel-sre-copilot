"""LangGraph StateGraph for the SRE-Copilot investigation agent.

Graph structure:
  START → tool_call_loop → [conditional: more tools?] → generate_report → END
                ↑___________________________________|
  (loops while LLM requests tool calls AND iteration < MAX_ITER)
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypedDict

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from src.agent.context_manager import ContextBudget
from src.agent.llm import (
    invoke_with_backoff,
    llm_settings,
    make_chat_model,
    rate_limit_wait_s,
)
from src.agent.llm_cache import request_stats
from src.agent.prompts import build_system_prompt
from src.agent.schemas import InvestigationReport
from src.agent.tools import make_tools
from src.datasources.live import ASTRONOMY_SHOP_SERVICES
from src.utils.cost import estimate_cost

if TYPE_CHECKING:
    from src.datasources.protocol import DataSource


class GraphState(TypedDict, total=False):
    """LangGraph state — TypedDict so all keys are preserved across nodes."""
    incident_id: str
    incident_start_ts: str
    incident_end_ts: str
    affected_namespace: str
    _investigation_start_ts: str
    messages: list[Any]
    tool_calls_log: list[dict[str, Any]]
    metrics_context: str
    traces_context: str
    logs_context: str
    hypotheses: list[dict[str, Any]]
    iteration_count: int
    token_usage: dict[str, int]
    final_report: InvestigationReport | None

log = structlog.get_logger()

AGENT_VERSION = "0.2.0"
MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "10"))
FAST_TOOL_ROUNDS = 2
# Force at least this many tool iterations, and at least one Prometheus metric sweep, before
# the agent is allowed to write a report. Without this the LLM tends to call get_service_topology
# once and then fabricate evidence (grounding_score=0.0).
MIN_TOOL_ITERATIONS = int(os.getenv("MIN_TOOL_ITERATIONS", "3"))


EventCallback = Callable[[dict[str, Any]], None]


def _add_usage(totals: dict[str, int], response: AIMessage) -> dict[str, int]:
    usage = getattr(response, "usage_metadata", None) or {}
    return {
        "prompt_tokens": totals.get("prompt_tokens", 0) + int(usage.get("input_tokens", 0)),
        "completion_tokens": totals.get("completion_tokens", 0)
        + int(usage.get("output_tokens", 0)),
        "llm_calls": totals.get("llm_calls", 0) + 1,
    }


def build_graph(
    ds: DataSource, on_event: EventCallback | None = None, *, react: bool = False,
    improved: bool = False, prior: bool = True,
    services: list[str] | None = None, namespace: str = "otel-demo",
) -> Any:  # noqa: ANN401
    """Build and compile the investigation StateGraph for the given DataSource.

    ``on_event`` receives every LLM step and tool call as it happens (used by the live demo).
    """

    def emit(event: dict[str, Any]) -> None:
        if on_event is not None:
            on_event(event)

    budget = ContextBudget()
    max_rounds = min(MAX_TOOL_ITERATIONS, FAST_TOOL_ROUNDS) if improved or react else (
        MAX_TOOL_ITERATIONS
    )
    tools = make_tools(
        ds, budget, improved=improved, prior=improved and prior,
        services=services, namespace=namespace,
    )

    settings = llm_settings()
    llm = make_chat_model(max_tokens=4096, concise=improved)
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    def run_tool(
        name: str, args: dict[str, Any], iteration: int, calls: list[dict[str, Any]],
    ) -> str:
        log.info("tool_call", name=name, iteration=iteration)
        started = time.perf_counter()
        repeated = improved and any(c["tool_name"] == name and c["args"] == args for c in calls)
        if repeated:
            result = "Identical call already answered. Use the earlier result."
        elif name in tool_map:
            try:
                result = str(tool_map[name].invoke(args))
            except Exception as error:
                result = f"[TOOL ERROR: {error}]"
        else:
            result = f"[UNKNOWN TOOL: {name}]"
        entry = {
            "iteration": iteration, "tool_name": name, "args": args,
            "result_preview": result[:200], "result_excerpt": result[:1200],
            "query_or_id": [] if repeated or (
                name == "rank_services_by_signal" and (services or namespace != "otel-demo")
            )
            else _extract_query_or_id(name, args),
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
        if improved:
            entry["evidence_ids"] = _evidence_ids(name, result)
        calls.append(entry)
        emit({"type": "tool_call", **entry})
        return result

    # ── Node: tool_call_loop ───────────────────────────────────────────────
    def tool_call_loop(state: GraphState) -> GraphState:
        iteration = state.get("iteration_count", 0)
        tool_calls_log: list[dict[str, Any]] = list(state.get("tool_calls_log", []))
        messages: list[Any] = list(state.get("messages", []))

        # First iteration: inject system + human messages
        if iteration == 0:
            system_msg = SystemMessage(content=build_system_prompt(
                start=state["incident_start_ts"],
                end=state["incident_end_ts"],
                namespace=state["affected_namespace"],
                max_iterations=max_rounds,
                react=react,
                improved=improved,
                prior=prior,
            ))
            human_content = (
                f"Investigate incident {state['incident_id']} "
                f"in namespace {state['affected_namespace']}. "
                f"Window: {state['incident_start_ts']} → {state['incident_end_ts']}. "
                "Identify the root cause and produce an InvestigationReport JSON."
            )
            if improved and not react:
                window = {"start": state["incident_start_ts"], "end": state["incident_end_ts"]}
                seeds = ["rank_request_rate_drops"]
                if prior:
                    seeds.insert(0, "rank_incident_anomalies")
                initial = [run_tool(name, window, 0, tool_calls_log) for name in seeds]
                human_content += "\nRecorded tool observations:\n" + "\n\n".join(initial)
            messages = [system_msg, HumanMessage(content=human_content)]

        # If the LLM tried to stop early (last msg is an AIMessage with no tool calls) but we
        # are forcing more investigation, nudge it to actually sweep metrics before concluding.
        elif messages and isinstance(messages[-1], AIMessage) and not getattr(
            messages[-1], "tool_calls", None
        ):
            nudge = (
                "Gather evidence with one metric tool before concluding." if improved else
                "You have not gathered enough grounded evidence yet. Before concluding, call "
                "query_prometheus_range to sweep error_rate, cpu_usage, memory_usage and "
                "pod_restarts across the main services, then inspect the top anomalies with "
                "search_traces / query_loki / get_pod_events. Do not fabricate evidence."
            )
            messages = messages + [HumanMessage(content=nudge)]

        # Call LLM
        t0 = time.perf_counter()
        response: AIMessage = invoke_with_backoff(llm_with_tools, messages)
        token_usage = _add_usage(state.get("token_usage", {}), response)
        emit({"type": "llm", "iteration": iteration,
              "elapsed_s": round(time.perf_counter() - t0, 2),
              "content": str(response.content)[:500],
              "n_tool_calls": len(getattr(response, "tool_calls", None) or [])})
        messages = messages + [response]

        # Execute any tool calls
        new_tool_messages: list[ToolMessage] = []
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc.get("args", {})
                tool_id = tc.get("id", f"call_{iteration}_{tool_name}")

                result_str = run_tool(tool_name, tool_args, iteration, tool_calls_log)
                new_tool_messages.append(ToolMessage(
                    content=result_str,
                    tool_call_id=tool_id,
                    name=tool_name,
                ))

        return {
            "messages": messages + new_tool_messages,
            "tool_calls_log": tool_calls_log,
            "iteration_count": iteration + 1,
            "token_usage": token_usage,
        }

    # ── Node: generate_report ──────────────────────────────────────────────
    def generate_report(state: GraphState) -> GraphState:
        messages: list[Any] = list(state.get("messages", []))
        inv_start = state.get("_investigation_start_ts", datetime.now(UTC).isoformat())

        # Ask LLM to produce the final structured report
        finalize = (
            "Based on all evidence gathered above, produce the final InvestigationReport JSON. "
            "Output ONLY the JSON object, no other text. "
        )
        if not react:
            finalize += (
                "Copy citation IDs exactly. Use metric, trace, log or k8s_event as signal_type."
                if improved else
                "Remember: every query_or_id in evidence must be an exact tool call you made."
            )
        if improved:
            finalize += (
                " Return at most three ranked causes, at most two citations per cause and "
                "at most two remediation steps. Keep each description to one sentence. "
                "Return only root_causes and remediation_steps; metadata is added separately."
            )
        messages_for_report = messages + [HumanMessage(content=finalize)]

        report_llm = make_chat_model(
            max_tokens=int(os.getenv("LLM_REPORT_MAX_TOKENS", "8192")),
            json_mode=True, concise=improved,
        )

        # One repair round: a report that fails the schema (or runs out of tokens) gets the
        # validation error back once. The grounding check and metrics stay external.
        usage_totals = dict(state.get("token_usage", {}))
        report: InvestigationReport | None = None
        content = ""
        repairs = int(os.getenv("LLM_REPORT_REPAIRS", "1"))
        for attempt in range(1 + (min(repairs, 1) if improved or react else repairs)):
            try:
                response: AIMessage = invoke_with_backoff(report_llm, messages_for_report)
            except Exception as e:
                if "LengthFinishReason" not in type(e).__name__:
                    raise
                usage = getattr(getattr(e, "completion", None), "usage", None)
                response = AIMessage(content="", usage_metadata={
                    "input_tokens": getattr(usage, "prompt_tokens", 0),
                    "output_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                })
            usage_totals = _add_usage(usage_totals, response)
            content = response.content if isinstance(response.content, str) else str(
                response.content)
            try:
                raw = json.loads(_strip_json_fences(content))
                raw.update({
                    "incident_id": state["incident_id"],
                    "investigation_start_ts": inv_start,
                    "investigation_end_ts": inv_start,
                    "llm_model": settings.model,
                    "agent_version": AGENT_VERSION,
                    "fault_type_classification": (
                        raw.get("root_causes", [{}])[0].get("fault_type", "unknown")
                        if raw.get("root_causes") else "unknown"
                    ),
                })
                report = InvestigationReport.model_validate(raw)
                break
            except (json.JSONDecodeError, ValidationError, IndexError, AttributeError) as e:
                error = (
                    "the answer hit the token limit before the JSON was complete"
                    if not content else str(e)[:1500]
                )
                log.error("report_parse_failed", attempt=attempt, error=error[:300],
                          content_preview=content[:200])
                emit({"type": "report_repair", "attempt": attempt, "error": error[:300]})
                messages_for_report = messages_for_report + [
                    AIMessage(content=content[:4000]),
                    HumanMessage(content=(
                        f"That report is invalid: {error}\n"
                        "Output the corrected InvestigationReport JSON only: at most 3 "
                        "root_causes, at most 4 evidence items each, signal_type one of "
                        "metric | trace | log | k8s_event, fault_type one of the allowed "
                        "values, every field of the schema present."
                    )),
                ]

        inv_end = datetime.now(UTC).isoformat()
        prompt_tokens = usage_totals["prompt_tokens"]
        completion_tokens = usage_totals["completion_tokens"]
        emit({"type": "report_llm", "prompt_tokens": prompt_tokens,
              "completion_tokens": completion_tokens, "llm_calls": usage_totals["llm_calls"]})
        latency_s = (
            datetime.fromisoformat(inv_end) - datetime.fromisoformat(inv_start)
        ).total_seconds() - rate_limit_wait_s()
        stats = request_stats()
        if stats is not None:
            latency_s += stats.replay_adjustment_s
        totals: dict[str, Any] = {
            "investigation_end_ts": inv_end,
            "latency_s": latency_s,
            "total_prompt_tokens": prompt_tokens,
            "total_completion_tokens": completion_tokens,
            "cost_usd": estimate_cost(prompt_tokens, completion_tokens),
        }
        if report is not None:
            report = report.model_copy(update=totals)
        else:
            # Unparseable answer = no hypothesis. model_construct skips the min_length=1 check
            # on root_causes so the harness scores it as a miss instead of crashing.
            report = InvestigationReport.model_construct(
                remediation_steps=[],
                grounding_score=0.0,
                agent_version=AGENT_VERSION,
                incident_id=state["incident_id"],
                investigation_start_ts=inv_start,
                root_causes=[],
                fault_type_classification="unknown",
                llm_model=settings.model,
                **totals,
            )

        return {"final_report": report, "token_usage": usage_totals}

    # ── Conditional edge ───────────────────────────────────────────────────
    def should_continue(state: GraphState) -> str:
        messages: list[Any] = state.get("messages", [])
        iteration = state.get("iteration_count", 0)

        if iteration >= max_rounds:
            log.info("iteration_limit_reached", iteration=iteration)
            return "generate_report"

        # Find last AIMessage — if it had tool_calls, they were just executed → keep looping.
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                if getattr(msg, "tool_calls", None):
                    return "tool_call_loop"
                break

        if react:
            return "generate_report"
        # LLM wants to stop. Force more investigation if it hasn't met the minimum: at least
        # MIN_TOOL_ITERATIONS iterations AND at least one Prometheus metric query.
        metric_calls = sum(
            1 for e in state.get("tool_calls_log", [])
            if str(e.get("tool_name", "")).startswith((
                "query_prometheus", "rank_services", "rank_incident", "rank_request",
            ))
        )
        if iteration < (1 if improved else MIN_TOOL_ITERATIONS) or metric_calls < 1:
            log.info("forcing_more_investigation", iteration=iteration, metric_calls=metric_calls)
            return "tool_call_loop"
        return "generate_report"

    # ── Build graph ────────────────────────────────────────────────────────
    graph = StateGraph(GraphState)
    graph.add_node("tool_call_loop", tool_call_loop)
    graph.add_node("generate_report", generate_report)

    graph.add_edge(START, "tool_call_loop")
    graph.add_conditional_edges(
        "tool_call_loop",
        should_continue,
        {"tool_call_loop": "tool_call_loop", "generate_report": "generate_report"},
    )
    graph.add_edge("generate_report", END)

    return graph.compile()


def _evidence_ids(tool_name: str, result: str) -> list[str]:
    prefix = {
        "rank_incident_anomalies": "metric:",
        "rank_request_rate_drops": "metric:",
        "get_trace": "trace:",
        "summarize_trace_latency": "trace:",
    }.get(tool_name)
    ids = []
    for line in result.splitlines():
        if tool_name == "rank_services_by_signal" and "citation: " in line:
            ids.append(line.rsplit("citation: ", 1)[-1])
        elif prefix and line.startswith(prefix):
            ids.append(line.split(maxsplit=1)[0])
    return list(dict.fromkeys(ids))


def _strip_json_fences(content: str) -> str:
    """Some OpenAI-compatible models wrap JSON mode output in ```json fences or add prose."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    first, last = text.find("{"), text.rfind("}")
    return text[first:last + 1] if first != -1 and last > first else text


def _extract_query_or_id(tool_name: str, args: dict) -> list[str]:  # type: ignore[type-arg]
    """Extract the query strings or IDs from tool args for grounding verification."""
    if tool_name in ("query_prometheus_range", "query_prometheus_instant"):
        return [args.get("query", "")]
    if tool_name == "rank_services_by_signal":
        from src.telemetry_queries import METRIC_QUERIES

        tpl = METRIC_QUERIES.get(str(args.get("signal", "")))
        return [tpl.format(svc=svc) for svc in ASTRONOMY_SHOP_SERVICES] if tpl else []
    if tool_name in ("search_traces",):
        return [f"search_traces:{args.get('service_name','')}" ]
    if tool_name == "get_trace":
        return [args.get("trace_id", "")]
    if tool_name == "query_loki":
        return [args.get("logql", "")]
    if tool_name == "get_pod_events":
        return [f"k8s_events:{args.get('namespace','')}/{args.get('pod_name_prefix','')}"]
    return []
