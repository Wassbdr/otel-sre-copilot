"""LangGraph StateGraph for the SRE-Copilot investigation agent.

Graph structure:
  START → tool_call_loop → [conditional: more tools?] → generate_report → END
                ↑___________________________________|
  (loops while LLM requests tool calls AND iteration < MAX_ITER)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, TypedDict

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from src.agent.context_manager import ContextBudget
from src.agent.prompts import build_system_prompt
from src.agent.schemas import InvestigationReport, initial_state
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
    final_report: InvestigationReport | None

log = structlog.get_logger()

MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "8"))


def build_graph(ds: "DataSource") -> StateGraph:
    """Build and compile the investigation StateGraph for the given DataSource."""

    budget = ContextBudget()
    tools = make_tools(ds, budget)

    # LLM: NVIDIA NIM API (OpenAI-compatible)
    llm = ChatOpenAI(
        model=os.getenv("NIM_MODEL", "meta/llama-3.1-70b-instruct"),
        openai_api_key=os.getenv("NIM_API_KEY", ""),
        openai_api_base=os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        temperature=0,
        max_tokens=4096,
    )
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

        # Call LLM
        response: AIMessage = llm_with_tools.invoke(messages)  # type: ignore[assignment]
        messages = messages + [response]

        # Execute any tool calls
        new_tool_messages: list[ToolMessage] = []
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc.get("args", {})
                tool_id = tc.get("id", f"call_{iteration}_{tool_name}")

                log.info("tool_call", name=tool_name, iteration=iteration)

                if tool_name in tool_map:
                    try:
                        result_str = tool_map[tool_name].invoke(tool_args)
                    except Exception as e:
                        result_str = f"[TOOL ERROR: {e}]"
                else:
                    result_str = f"[UNKNOWN TOOL: {tool_name}]"

                # Record tool call for grounding verification
                tool_calls_log.append({
                    "iteration": iteration,
                    "tool_name": tool_name,
                    "args": tool_args,
                    "result_preview": str(result_str)[:200],
                    # Store exact query/id strings for grounding check
                    "query_or_id": _extract_query_or_id(tool_name, tool_args),
                })

                new_tool_messages.append(ToolMessage(
                    content=str(result_str),
                    tool_call_id=tool_id,
                    name=tool_name,
                ))

        return {
            "messages": messages + new_tool_messages,
            "tool_calls_log": tool_calls_log,
            "iteration_count": iteration + 1,
        }

    # ── Node: generate_report ──────────────────────────────────────────────
    def generate_report(state: GraphState) -> GraphState:
        messages: list = list(state.get("messages", []))
        inv_start = state.get("_investigation_start_ts", datetime.now(timezone.utc).isoformat())

        # Ask LLM to produce the final structured report
        finalize_msg = HumanMessage(
            content=(
                "Based on all evidence gathered above, produce the final InvestigationReport JSON. "
                "Output ONLY the JSON object, no other text. "
                "Remember: every query_or_id in evidence must be an exact tool call you made."
            )
        )
        messages_for_report = messages + [finalize_msg]

        report_llm = ChatOpenAI(
            model=os.getenv("NIM_MODEL", "meta/llama-3.1-70b-instruct"),
            openai_api_key=os.getenv("NIM_API_KEY", ""),
            openai_api_base=os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            temperature=0,
            max_tokens=2048,
            model_kwargs={"response_format": {"type": "json_object"}},
        )

        response: AIMessage = report_llm.invoke(messages_for_report)  # type: ignore[assignment]
        inv_end = datetime.now(timezone.utc).isoformat()

        # Parse and validate
        content = response.content if isinstance(response.content, str) else str(response.content)

        # Inject timing and token metadata
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = usage.get("input_tokens", 0) if usage else 0
        completion_tokens = usage.get("output_tokens", 0) if usage else 0
        latency_s = (
            datetime.fromisoformat(inv_end) - datetime.fromisoformat(inv_start)
        ).total_seconds()

        try:
            raw = json.loads(content)
            raw.update({
                "incident_id": state["incident_id"],
                "investigation_start_ts": inv_start,
                "investigation_end_ts": inv_end,
                "latency_s": latency_s,
                "total_prompt_tokens": prompt_tokens,
                "total_completion_tokens": completion_tokens,
                "cost_usd": estimate_cost(prompt_tokens, completion_tokens),
                "llm_model": os.getenv("NIM_MODEL", "meta/llama-3.1-70b-instruct"),
                "agent_version": "0.1.0",
                "fault_type_classification": (
                    raw.get("root_causes", [{}])[0].get("fault_type", "unknown")
                    if raw.get("root_causes") else "unknown"
                ),
            })
            report = InvestigationReport.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, IndexError) as e:
            log.error("report_parse_failed", error=str(e), content_preview=content[:300])
            # Return a minimal valid report rather than crashing
            report = InvestigationReport(
                incident_id=state["incident_id"],
                investigation_start_ts=inv_start,
                investigation_end_ts=inv_end,
                root_causes=[],
                fault_type_classification="unknown",
                latency_s=latency_s,
            )

        return {"final_report": report}

    # ── Conditional edge ───────────────────────────────────────────────────
    def should_continue(state: GraphState) -> str:
        messages: list = state.get("messages", [])
        iteration = state.get("iteration_count", 0)

        if iteration >= MAX_TOOL_ITERATIONS:
            log.info("iteration_limit_reached", iteration=iteration)
            return "generate_report"

        last_msg = messages[-1] if messages else None
        if isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None):
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
