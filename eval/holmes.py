from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from contextvars import copy_context
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from time import perf_counter
from typing import Any

import httpx

from eval.grounding_verifier import verify
from eval.metrics import ScenarioResult, compute_per_scenario
from eval.scenario_runner import opaque_incident_id, write_json_atomic
from src.agent.graph import _strip_json_fences
from src.agent.llm import DEFAULT_BASE_URL, llm_settings
from src.agent.llm_cache import CachedChatClient, request_scope
from src.agent.prompts import INVESTIGATION_REPORT_SCHEMA, _query_catalog
from src.agent.schemas import InvestigationReport
from src.replay_server import make_server
from src.utils.cost import estimate_cost


def _replay_evidence(
    path: str, params: dict[str, list[str]], payload: dict[str, Any],
) -> dict[str, object] | None:
    traces = [trace["traceID"] for trace in payload.get("traces", [])]
    if match := re.fullmatch(r"/api/(?:v2/)?traces/([0-9a-fA-F]+)", path):
        traces.append(match[1])
    queries = (
        params.get("query", []) if path in {
            "/api/v1/query", "/api/v1/query_range", "/loki/api/v1/query_range",
        } else []
    )
    queries = [q for q in queries if q != "up" and payload.get("data", {}).get("result")]
    if not traces and not queries:
        return None
    return {"tool_name": path, "query_or_id": queries + traces,
            "evidence_ids": [f"trace:{trace}" for trace in traces]}


def run_holmes(snapshot: Path, trace_path: Path, scope: str) -> dict[str, Any]:
    settings = llm_settings()
    if settings.base_url.rstrip("/") != DEFAULT_BASE_URL or not settings.api_key:
        raise ValueError("Set NIM_API_KEY and use the default NIM endpoint for HolmesGPT.")
    python = os.getenv("HOLMES_PYTHON")
    if not python:
        raise ValueError("Set HOLMES_PYTHON to the Python interpreter with holmesgpt==0.48.0.")
    meta = json.loads((snapshot / "metadata.json").read_text())
    truth = json.loads((snapshot / "ground_truth.json").read_text())
    scenario = truth["scenario_id"]
    start, end = meta["window_start"], meta["window_end"]
    token = secrets.token_urlsafe(24)
    evidence: list[dict[str, object]] = []
    report_start = datetime.now(UTC).isoformat()
    started = perf_counter()

    def observe(path: str, params: dict[str, list[str]], payload: dict[str, Any]) -> None:
        if item := _replay_evidence(path, params, payload):
            evidence.append(item)

    with request_scope(scope) as stats, CachedChatClient(timeout=90) as client:
        ctx = copy_context()

        def complete(body: bytes, authorization: str) -> tuple[int, bytes]:
            if not secrets.compare_digest(authorization, f"Bearer {token}"):
                return 401, b'{"error":{"message":"Invalid replay authorization"}}'
            try:
                payload = json.loads(body)
                if payload.get("model") != settings.model or payload.get("stream"):
                    return 400, b'{"error":{"message":"Use the benchmark model without streaming"}}'
                response = ctx.copy().run(
                    client.post, f"{DEFAULT_BASE_URL}/chat/completions", json=payload,
                    headers={"Authorization": f"Bearer {settings.api_key}"},
                )
                if response.status_code >= 400:
                    error = {"error": {"message": f"NIM returned HTTP {response.status_code}"}}
                    return response.status_code, json.dumps(error).encode()
                return response.status_code, response.content
            except (ValueError, AttributeError):
                return 400, b'{"error":{"message":"Invalid completion request"}}'
            except httpx.RequestError:
                return 504, b'{"error":{"message":"NIM request timed out or disconnected"}}'

        trace_path.parent.mkdir(parents=True, exist_ok=True)
        prompt = (
            f"Investigate the incident in {meta.get('namespace', 'otel-demo')} "
            f"between {start} and {end} using the three recorded telemetry backends. "
            "Return only JSON with up to three ranked service and fault-type pairs, "
            "evidence, and remediation. Cite exact queried expressions or retrieved trace IDs. "
            f"Match this schema: {INVESTIGATION_REPORT_SCHEMA}\n"
            "Available recorded metric query templates, substituting <SVC>:\n"
            f"{_query_catalog()}"
        )
        output = trace_path.with_name("holmes.json")
        worker = Path(__file__).resolve().parents[1] / "scripts/holmes_worker.py"
        with make_server(snapshot, "127.0.0.1", 0, observe=observe, complete=complete) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            env = {
                "PATH": os.defpath,
                "HOME": str(Path.home()),
                "LITELLM_LOCAL_MODEL_COST_MAP": "True",
                "NVIDIA_NIM_API_KEY": token,
            }
            try:
                with trace_path.with_name("holmes.log").open("w") as log:
                    subprocess.run(
                        [python, str(worker), f"http://127.0.0.1:{server.server_port}",
                         settings.model, prompt, str(output.resolve())],
                        env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600,
                    )
            finally:
                server.shutdown()
                thread.join()

    data = json.loads(output.read_text())
    if not data.get("num_llm_calls"):
        raise ValueError("HolmesGPT did not report a model call. Check holmes.log.")
    metadata = {
        "incident_id": opaque_incident_id(scenario),
        "investigation_start_ts": report_start,
        "investigation_end_ts": datetime.now(UTC).isoformat(),
        "llm_model": settings.model,
        "agent_version": "holmesgpt-0.48.0",
        "latency_s": max(0, perf_counter() - started - stats.wait_s
                         - data.get("llm_rate_limit_wait_ms", 0) / 1000
                         + stats.replay_adjustment_s),
        "total_prompt_tokens": data["prompt_tokens"],
        "total_completion_tokens": data["completion_tokens"],
        "cost_usd": estimate_cost(data["prompt_tokens"], data["completion_tokens"]),
    }
    try:
        payload = json.loads(_strip_json_fences(data.get("result") or ""))
        metadata["fault_type_classification"] = payload["root_causes"][0]["fault_type"]
        report = InvestigationReport.model_validate({**payload, **metadata})
    except (ValueError, TypeError, KeyError, IndexError):
        report = InvestigationReport.model_construct(
            **{**metadata, "fault_type_classification": "unknown"}, root_causes=[],
        )
    grounding = verify(report, evidence)
    report.grounding_score = grounding.grounding_score
    metrics = compute_per_scenario(
        ScenarioResult(scenario, report, truth, grounding.grounding_score),
    )
    metrics.update(
        llm_calls=data["num_llm_calls"], evidence_count=grounding.total_count,
        verified_evidence_count=grounding.verified_count,
        rate_limit_wait_s=stats.wait_s + data.get("llm_rate_limit_wait_ms", 0) / 1000,
        cached_requests=stats.cached_requests,
    )
    write_json_atomic(trace_path, {
        "scenario_id": scenario, "snapshot_dir": str(snapshot), "model": settings.model,
        "report": report.model_dump(mode="json"), "ground_truth": truth,
        "tool_calls": evidence, "metrics": metrics,
    })
    return metrics
