"""Deterministic stand-in for a tool-calling chat model.

Two modes:
- ``FakeChatModel(responses=[...])`` replays scripted ``AIMessage`` objects in order (unit tests).
- ``FakeChatModel.from_env()`` (``LLM_PROVIDER=fake``) follows a fixed investigation script so the
  whole graph, the grounding verifier and the eval harness run end-to-end without a key.
  Its answers are canned, so its accuracy means nothing: it is a plumbing test, not a model.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from src.telemetry_queries import METRIC_QUERIES

_WINDOW_RE = re.compile(r"Window:\s*(\S+)\s*→\s*(\S+?)\.?\s")
_NAMESPACE_RE = re.compile(r"in namespace (\S+?)\.")


class FakeChatModel:
    """Minimal subset of the LangChain chat-model API used by the graph."""

    def __init__(
        self, responses: Sequence[AIMessage] | None = None, service: str = "frontend"
    ) -> None:
        self._responses = list(responses or [])
        self._service = service
        self.calls: list[list[BaseMessage]] = []

    @classmethod
    def from_env(cls) -> FakeChatModel:
        return cls()

    def bind_tools(self, tools: Sequence[Any]) -> FakeChatModel:  # noqa: ARG002
        return self

    def invoke(self, messages: Sequence[BaseMessage]) -> AIMessage:
        self.calls.append(list(messages))
        if self._responses:
            return self._responses.pop(0)
        return self._scripted(list(messages))

    def _scripted(self, messages: list[BaseMessage]) -> AIMessage:
        start, end, namespace = _incident_context(messages)
        n_ai = sum(1 for m in messages if isinstance(m, AIMessage))
        svc = self._service
        error_q = METRIC_QUERIES["error_rate"].format(svc=svc)
        plan: list[tuple[str, dict[str, Any]]] = [
            ("get_service_topology", {"namespace": namespace}),
            ("query_prometheus_range", {"query": error_q, "start": start, "end": end}),
            ("search_traces", {"service_name": svc, "start": start, "end": end,
                               "error_only": True}),
        ]
        last = messages[-1] if messages else None
        wants_report = isinstance(last, HumanMessage) and "InvestigationReport JSON" in str(
            last.content
        ) and n_ai > 0
        if n_ai < len(plan) and not wants_report:
            name, args = plan[n_ai]
            return AIMessage(
                content="",
                tool_calls=[{"name": name, "args": args, "id": f"fake_{n_ai}", "type":
                             "tool_call"}],
                usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            )
        if not any(isinstance(m, ToolMessage) for m in messages) or not wants_report:
            return AIMessage(content="Done investigating.")
        report = {
            "root_causes": [{
                "rank": 1, "service": svc, "fault_type": "unknown", "confidence": 0.1,
                "description": "Scripted fake LLM answer (no reasoning).",
                "evidence": [{"signal_type": "metric", "query_or_id": error_q,
                              "observed_value": "see tool output"}],
            }],
            "remediation_steps": ["Configure a real LLM endpoint (LLM_API_KEY / NIM_API_KEY)."],
        }
        return AIMessage(content=json.dumps(report))


def _incident_context(messages: list[BaseMessage]) -> tuple[str, str, str]:
    for m in messages:
        if isinstance(m, HumanMessage):
            text = str(m.content) + " "
            w = _WINDOW_RE.search(text)
            ns = _NAMESPACE_RE.search(text)
            if w:
                return w.group(1), w.group(2), ns.group(1) if ns else "otel-demo"
    return "", "", "otel-demo"
