"""Evaluation metrics for root-cause analysis quality.

All metrics operate on lists of (InvestigationReport, ground_truth_dict) pairs.
Metrics are never self-reported by the agent — this module is the single source of truth.

Metrics:
  accuracy_at_k(k)   — fraction where correct (service, fault_type) is in top-k
  mrr                — mean reciprocal rank of correct hypothesis
  service_at_k(k)    — fraction where the faulty service is in top-k, fault type ignored
  fault_type_accuracy — fraction where top-1 fault_type matches ground truth
  mean_latency_s     — mean wall-clock investigation latency
  total_cost_usd     — total cost across all scenarios
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.agent.schemas import InvestigationReport
from src.datasources.live import ASTRONOMY_SHOP_SERVICES

_SERVICE_ALIASES = {
    compact: service
    for service in ASTRONOMY_SHOP_SERVICES
    for compact in (service.replace("-", ""), service.replace("-", "") + "service")
}


def canonical_service(service: str) -> str:
    label = service.strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    return _SERVICE_ALIASES.get(label, service)


@dataclass
class EvalMetrics:
    n_scenarios: int
    accuracy_at_1: float
    accuracy_at_3: float
    mrr: float
    fault_type_accuracy: float
    mean_grounding_score: float
    mean_latency_s: float
    total_cost_usd: float
    mean_cost_usd: float

    def as_dict(self) -> dict[str, object]:
        return {
            "n_scenarios": self.n_scenarios,
            "accuracy_at_1": round(self.accuracy_at_1, 4),
            "accuracy_at_3": round(self.accuracy_at_3, 4),
            "mrr": round(self.mrr, 4),
            "fault_type_accuracy": round(self.fault_type_accuracy, 4),
            "mean_grounding_score": round(self.mean_grounding_score, 4),
            "mean_latency_s": round(self.mean_latency_s, 2),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "mean_cost_usd": round(self.mean_cost_usd, 6),
        }


@dataclass
class ScenarioResult:
    scenario_id: str
    report: InvestigationReport
    ground_truth: dict[str, Any]
    grounding_score: float   # injected by harness after grounding_verifier.verify()


def compute_metrics(results: list[ScenarioResult]) -> EvalMetrics:
    """Compute all evaluation metrics over a list of scenario results."""
    if not results:
        return EvalMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    n = len(results)
    acc1_sum = 0.0
    acc3_sum = 0.0
    mrr_sum = 0.0
    fault_type_sum = 0.0
    grounding_sum = 0.0
    latency_sum = 0.0
    cost_sum = 0.0

    for sr in results:
        row = compute_per_scenario(sr)
        acc1_sum += float(row["accuracy_at_1"])
        acc3_sum += float(row["accuracy_at_3"])
        mrr_sum += float(row["mrr"])
        fault_type_sum += float(row["fault_type_correct"])

        grounding_sum += sr.grounding_score
        latency_sum += sr.report.latency_s
        cost_sum += sr.report.cost_usd

    return EvalMetrics(
        n_scenarios=n,
        accuracy_at_1=acc1_sum / n,
        accuracy_at_3=acc3_sum / n,
        mrr=mrr_sum / n,
        fault_type_accuracy=fault_type_sum / n,
        mean_grounding_score=grounding_sum / n,
        mean_latency_s=latency_sum / n,
        total_cost_usd=cost_sum,
        mean_cost_usd=cost_sum / n,
    )


def compute_per_scenario(sr: ScenarioResult) -> dict[str, Any]:
    """Score the fraction of true causes covered at each rank, averaged per snapshot."""
    gt_service = sr.ground_truth.get("fault_service", "")
    gt_fault = sr.ground_truth.get("fault_type", "")
    faults = sr.ground_truth.get("faults") or [sr.ground_truth]
    true_pairs = {
        (canonical_service(fault.get("fault_service", "")), fault.get("fault_type", ""))
        for fault in faults
    }
    true_services = {service for service, _ in true_pairs}
    rc = sr.report.root_causes or []
    pairs = [(canonical_service(h.service), h.fault_type) for h in rc[:3]]
    services = [service for service, _ in pairs]
    return {
        "scenario_id": sr.scenario_id,
        "ground_truth_service": gt_service,
        "ground_truth_fault_type": gt_fault,
        "predicted_service": services[0] if services else "none",
        "predicted_fault_type": rc[0].fault_type if rc else "unknown",
        "accuracy_at_1": len(true_pairs.intersection(pairs[:1])) / len(true_pairs),
        "accuracy_at_3": len(true_pairs.intersection(pairs)) / len(true_pairs),
        "mrr": sum(1 / (pairs.index(pair) + 1) for pair in true_pairs if pair in pairs)
        / len(true_pairs),
        "service_at_1": len(true_services.intersection(services[:1])) / len(true_services),
        "service_at_3": len(true_services.intersection(services)) / len(true_services),
        "fault_type_correct": int(bool(rc) and rc[0].fault_type in {typ for _, typ in true_pairs}),
        "grounding_score": sr.grounding_score,
        "latency_s": sr.report.latency_s,
        "cost_usd": sr.report.cost_usd,
        "prompt_tokens": sr.report.total_prompt_tokens,
        "completion_tokens": sr.report.total_completion_tokens,
        "total_tokens": sr.report.total_prompt_tokens + sr.report.total_completion_tokens,
        "hallucination_warning": sr.grounding_score < 0.8,
    }
