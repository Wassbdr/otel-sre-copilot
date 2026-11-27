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
from src.agent.llm import llm_settings, make_chat_model
from src.agent.prompts import build_system_prompt
from src.agent.schemas import InvestigationReport
from src.agent.tools import make_tools
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

MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "8"))
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


def build_graph(ds: DataSource, on_event: EventCallback | None = None) -> StateGraph:
    """Build and compile the investigation StateGraph for the given DataSource.

    ``on_event`` receives every LLM step and tool call as it happens (used by the live demo).
    """

    def emit(event: dict[str, Any]) -> None:
        if on_event is not None:
            on_event(event)

    budget = ContextBudget()
    tools = make_tools(ds, budget)

    settings = llm_settings()
    llm = make_chat_model(max_tokens=4096)
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    # ── Node: tool_call_loop ───────────────────────────────────────────────
    def tool_call_loop(state: GraphState) -> GraphState:
        iteration = state.get("iteration_count", 0)
        tool_calls_log: list[dict] = list(state.get("tool_calls_log", []))
        messages: list = list(state.get("messages", []))

        # First iteration: inject system + human messages
        if iteration == 0:
            system_msg = SystemMessage(content=build_system_prompt(
                start=state["incident_start_ts"],
                end=state["incident_end_ts"],
                namespace=state["affected_namespace"],
                max_iterations=MAX_TOOL_ITERATIONS,
            ))
            human_msg = HumanMessage(
                content=f"Investigate incident {state['incident_id']} "
                        f"in namespace {state['affected_namespace']}. "
                        f"Window: {state['incident_start_ts']} → {state['incident_end_ts']}. "
                        "Identify the root cause and produce an InvestigationReport JSON."
            )
            messages = [system_msg, human_msg]

        # If the LLM tried to stop early (last msg is an AIMessage with no tool calls) but we
        # are forcing more investigation, nudge it to actually sweep metrics before concluding.
        elif messages and isinstance(messages[-1], AIMessage) and not getattr(
            messages[-1], "tool_calls", None
        ):
            messages = messages + [HumanMessage(content=(
                "You have not gathered enough grounded evidence yet. Before concluding, call "
                "query_prometheus_range to sweep error_rate, cpu_usage, memory_usage and "
                "pod_restarts across the main services, then inspect the top anomalies with "
                "search_traces / query_loki / get_pod_events. Do not fabricate evidence."
            ))]

        # Call LLM
        t0 = time.perf_counter()
        response: AIMessage = llm_with_tools.invoke(messages)  # type: ignore[assignment]
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

                log.info("tool_call", name=tool_name, iteration=iteration)

                t_tool = time.perf_counter()
                if tool_name in tool_map:
                    try:
                        result_str = tool_map[tool_name].invoke(tool_args)
                    except Exception as e:
                        result_str = f"[TOOL ERROR: {e}]"
                else:
                    result_str = f"[UNKNOWN TOOL: {tool_name}]"

                # Record tool call for grounding verification
                entry = {
                    "iteration": iteration,
                    "tool_name": tool_name,
                    "args": tool_args,
                    "result_preview": str(result_str)[:200],
                    # Store exact query/id strings for grounding check
                    "query_or_id": _extract_query_or_id(tool_name, tool_args),
                    # Longer excerpt for human-readable traces (demo); not used for grounding.
                    "result_excerpt": str(result_str)[:1200],
                    "elapsed_s": round(time.perf_counter() - t_tool, 3),
                }
                tool_calls_log.append(entry)
                emit({"type": "tool_call", **entry})

                new_tool_messages.append(ToolMessage(
                    content=str(result_str),
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
        messages: list = list(state.get("messages", []))
        inv_start = state.get("_investigation_start_ts", datetime.now(UTC).isoformat())

        # Ask LLM to produce the final structured report
        finalize_msg = HumanMessage(
            content=(
                "Based on all evidence gathered above, produce the final InvestigationReport JSON. "
                "Output ONLY the JSON object, no other text. "
                "Remember: every query_or_id in evidence must be an exact tool call you made."
            )
        )
        messages_for_report = messages + [finalize_msg]

        report_llm = make_chat_model(max_tokens=int(os.getenv("LLM_REPORT_MAX_TOKENS", "4096")),
                                     json_mode=True)

        response: AIMessage = report_llm.invoke(messages_for_report)  # type: ignore[assignment]
        inv_end = datetime.now(UTC).isoformat()

        # Parse and validate
        content = response.content if isinstance(response.content, str) else str(response.content)

        # Token totals cover every LLM call of the investigation, not just the report call.
        usage_totals = _add_usage(state.get("token_usage", {}), response)
        prompt_tokens = usage_totals["prompt_tokens"]
        completion_tokens = usage_totals["completion_tokens"]
        emit({"type": "report_llm", "prompt_tokens": prompt_tokens,
              "completion_tokens": completion_tokens, "llm_calls": usage_totals["llm_calls"]})
        latency_s = (
            datetime.fromisoformat(inv_end) - datetime.fromisoformat(inv_start)
        ).total_seconds()

        try:
            raw = json.loads(_strip_json_fences(content))
            raw.update({
                "incident_id": state["incident_id"],
                "investigation_start_ts": inv_start,
                "investigation_end_ts": inv_end,
                "latency_s": latency_s,
                "total_prompt_tokens": prompt_tokens,
                "total_completion_tokens": completion_tokens,
                "cost_usd": estimate_cost(prompt_tokens, completion_tokens),
                "llm_model": settings.model,
                "agent_version": "0.1.0",
                "fault_type_classification": (
                    raw.get("root_causes", [{}])[0].get("fault_type", "unknown")
                    if raw.get("root_causes") else "unknown"
                ),
            })
            report = InvestigationReport.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, IndexError) as e:
            log.error("report_parse_failed", error=str(e), content_preview=content[:300])
            # Unparseable answer = no hypothesis. model_construct skips the min_length=1 check
            # on root_causes so the harness scores it as a miss instead of crashing.
            report = InvestigationReport.model_construct(
                remediation_steps=[],
                grounding_score=0.0,
                cost_usd=0.0,
                agent_version="0.1.0",
                incident_id=state["incident_id"],
                investigation_start_ts=inv_start,
                investigation_end_ts=inv_end,
                root_causes=[],
                fault_type_classification="unknown",
                latency_s=latency_s,
                total_prompt_tokens=prompt_tokens,
                total_completion_tokens=completion_tokens,
                llm_model=settings.model,
            )

        return {"final_report": report, "token_usage": usage_totals}

    # ── Conditional edge ───────────────────────────────────────────────────
    def should_continue(state: GraphState) -> str:
        messages: list = state.get("messages", [])
        iteration = state.get("iteration_count", 0)

        if iteration >= MAX_TOOL_ITERATIONS:
            log.info("iteration_limit_reached", iteration=iteration)
            return "generate_report"

        # Find last AIMessage — if it had tool_calls, they were just executed → keep looping.
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                if getattr(msg, "tool_calls", None):
                    return "tool_call_loop"
                break

        # LLM wants to stop. Force more investigation if it hasn't met the minimum: at least
        # MIN_TOOL_ITERATIONS iterations AND at least one Prometheus metric query.
        metric_calls = sum(
            1 for e in state.get("tool_calls_log", [])
            if str(e.get("tool_name", "")).startswith("query_prometheus")
        )
        if iteration < MIN_TOOL_ITERATIONS or metric_calls < 1:
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
    if tool_name in ("search_traces",):
        return [f"search_traces:{args.get('service_name','')}" ]
    if tool_name == "get_trace":
        return [args.get("trace_id", "")]
    if tool_name == "query_loki":
        return [args.get("logql", "")]
    if tool_name == "get_pod_events":
        return [f"k8s_events:{args.get('namespace','')}/{args.get('pod_name_prefix','')}"]
    return []
