"""Typed entry points for live and snapshot investigations."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.grounding_verifier import verify
from src.agent.graph import build_graph
from src.agent.llm import llm_settings
from src.agent.schemas import InvestigationReport, initial_state
from src.datasources.live import LiveDataSource
from src.datasources.protocol import DataSource
from src.datasources.replay import ReplayDataSource


class InvestigationError(RuntimeError):
    """An investigation could not be started or did not produce a report."""


def investigate(
    source: DataSource, *, start: datetime, end: datetime,
    namespace: str = "otel-demo", incident_id: str = "incident",
    services: list[str] | None = None,
) -> InvestigationReport:
    if start.utcoffset() is None or end.utcoffset() is None or end <= start:
        raise InvestigationError("Use timezone-aware timestamps with --end later than --start.")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", namespace):
        raise InvestigationError("Kubernetes namespaces use lowercase letters, digits and '-'.")
    if services and any(not re.fullmatch(r"[A-Za-z0-9_-]+", service) for service in services):
        raise InvestigationError("Use service names with letters, digits, underscores or hyphens.")
    settings = llm_settings()
    if not settings.is_fake and not settings.api_key:
        raise InvestigationError(
            "Set NIM_API_KEY or LLM_API_KEY, or use LLM_PROVIDER=fake for an offline smoke test."
        )
    state = initial_state(
        incident_id, start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat(), namespace,
    )
    state["_investigation_start_ts"] = datetime.now(UTC).isoformat()
    try:
        result: dict[str, Any] = build_graph(
            source, improved=True, services=services, namespace=namespace,
        ).invoke(state)
    except Exception as error:
        raise InvestigationError(
            f"Investigation failed ({type(error).__name__}). Check the LLM endpoint, key, "
            "and model; for live mode, also check telemetry URLs and cluster access."
        ) from error
    report = result.get("final_report")
    if not isinstance(report, InvestigationReport) or not report.root_causes:
        raise InvestigationError(
            "The model did not produce a usable report. Check model support for tool calls "
            "and JSON output, then retry."
        )
    report.grounding_score = verify(report, result["tool_calls_log"]).grounding_score
    return report


def investigate_snapshot(
    snapshot: str | Path, *, incident_id: str = "snapshot",
) -> InvestigationReport:
    path = Path(snapshot).expanduser()
    try:
        meta = json.loads((path / "metadata.json").read_text())
        start = datetime.fromisoformat(meta["window_start"])
        end = datetime.fromisoformat(meta["window_end"])
        namespace = str(meta.get("namespace", "otel-demo"))
        services = meta.get("services_snapshotted")
        if services is not None and (
            not isinstance(services, list) or not all(isinstance(s, str) for s in services)
        ):
            raise ValueError("invalid service list")
        if not (path / "prometheus/raw_queries.json").is_file():
            raise ValueError("missing Prometheus data")
        source = ReplayDataSource(path)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise InvestigationError(
            f"Cannot read snapshot {path}. Use a captured directory with metadata.json "
            "containing window_start and window_end, and prometheus/raw_queries.json."
        ) from error
    return investigate(
        source, start=start, end=end, namespace=namespace, incident_id=incident_id,
        services=services,
    )


def investigate_live(
    *, start: datetime, end: datetime, namespace: str = "otel-demo",
    incident_id: str = "incident", prometheus_url: str | None = None,
    loki_url: str | None = None, tempo_url: str | None = None,
    services: list[str] | None = None,
) -> InvestigationReport:
    with LiveDataSource(
        prometheus_url=prometheus_url, loki_url=loki_url, tempo_url=tempo_url,
        topology={service: [] for service in services} if services else None,
    ) as source:
        return investigate(
            source, start=start, end=end, namespace=namespace, incident_id=incident_id,
            services=services,
        )
