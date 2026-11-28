"""Inject Chaos Mesh faults, wait for recovery, then snapshot telemetry.

A scenario contains metadata and one chaos_manifest, or metadata and a faults list.
Each entry in faults provides fault_service, fault_type and chaos_manifest.

Usage:
    python scripts/inject_and_snapshot.py \\
        --scenario scenarios/mvp/001-checkoutservice-pod-crash.yaml \\
        [--dry-run]   # validate YAML without injecting
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import structlog
import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.telemetry_queries import METRIC_QUERIES

load_dotenv()

log = structlog.get_logger()

# fault_type -> candidate signals whose value should make the faulted service an outlier
# (high OR low: a pod_crash makes request_rate drop, cpu_stress makes cpu spike; both are
# |z|-outliers vs the other services in the fault window).
_FAULT_SIGNALS: dict[str, list[str]] = {
    "pod_crash": ["pod_restarts", "request_rate", "error_rate"],
    "high_latency": ["p99_latency_ms"],
    "http_abort": ["error_rate", "p99_latency_ms"],
    "cpu_stress": ["cpu_usage"],
    "memory_stress": ["memory_usage"],
}

_KUBE_CONTEXT = os.getenv("KUBE_CONTEXT", "kind-otel-sre-copilot")

_SNAPSHOTS_DIR = Path("snapshots")


def _derive_fault_type(kind: str, chaos: dict[str, object]) -> str:
    """Fallback fault_type from the chaos manifest (used only if the scenario omits one)."""
    spec = chaos.get("spec", {}) if isinstance(chaos.get("spec"), dict) else {}
    if kind == "PodChaos":
        return "pod_crash"
    if kind == "HTTPChaos":
        return "http_abort"
    if kind == "StressChaos":
        stressors = spec.get("stressors", {}) if isinstance(spec, dict) else {}
        return "memory_stress" if "memory" in stressors else "cpu_stress"
    if kind == "NetworkChaos":
        # delay → latency; loss/corrupt/partition → connectivity abort
        return "high_latency" if spec.get("action") == "delay" else "http_abort"
    return "unknown"


def parse_scenario(
    path: Path,
) -> tuple[dict[str, object], list[tuple[dict[str, object], dict[str, object]]]]:
    with open(path) as f:
        doc = yaml.safe_load(f)
    meta = doc.get("metadata", {})
    faults = doc.get("faults")
    if not meta or bool(faults) == bool(doc.get("chaos_manifest")):
        raise ValueError(f"{path}: provide metadata and either chaos_manifest or faults")
    if not faults:
        return meta, [(meta, doc["chaos_manifest"])]
    if len(faults) < 2 or any(not fault.get("chaos_manifest") for fault in faults):
        raise ValueError(f"{path}: provide at least two faults, each with a chaos_manifest")
    return meta, [(fault, fault["chaos_manifest"]) for fault in faults]


def extract_ground_truth(
    meta: dict[str, object],
    chaos: dict[str, object],
    injection_ts: str,
    recovery_ts: str,
) -> dict[str, object]:
    """Build ground truth JSON. fault_type/fault_service are pinned in the versioned scenario
    YAML (reproducible, not agent-influenced); the chaos manifest is the *mechanism* and is
    only used to derive fault_type as a fallback. The chaos kind is recorded for traceability.
    """
    kind = str(chaos.get("kind", ""))
    fault_type = str(meta.get("fault_type") or _derive_fault_type(kind, chaos))

    selector = (
        chaos.get("spec", {}).get("selector", {}).get("labelSelectors", {})  # type: ignore[union-attr]
        or {}
    )
    fault_service = str(
        meta.get("fault_service")
        or selector.get("app.kubernetes.io/component")
        or selector.get("app", "unknown")
    )

    return {
        "scenario_id": str(meta.get("scenario_id", "")),
        "fault_service": fault_service,
        "fault_type": fault_type,
        "chaos_kind": kind,
        "injection_ts": injection_ts,
        "recovery_ts": recovery_ts,
        "seed": int(meta.get("seed", 42)),
        "chaos_manifest_hash": hashlib.sha256(
            json.dumps(chaos, sort_keys=True).encode()
        ).hexdigest()[:16],
    }


# The kind node runs the whole otel-demo + LGTM stack on a constrained host; under load the
# apiserver intermittently drops connections. These are transient; retry instead of aborting
# a multi-minute capture on a single dropped packet.
_KUBECTL_RETRY_MARKERS = (
    "connection reset by peer",
    "EOF",
    "i/o timeout",
    "TLS handshake timeout",
    "connection refused",
    "Unable to connect to the server",
)


def run_kubectl(
    args: list[str], dry_run: bool = False, retries: int = 4, backoff_s: float = 5.0
) -> subprocess.CompletedProcess[str]:
    cmd = ["kubectl", "--context", _KUBE_CONTEXT] + args
    if dry_run:
        log.info("dry_run_kubectl", cmd=" ".join(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    last_stderr = ""
    for attempt in range(1, retries + 1):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return result
        last_stderr = result.stderr
        transient = any(m in result.stderr for m in _KUBECTL_RETRY_MARKERS)
        if transient and attempt < retries:
            log.warning("kubectl_transient_retry", attempt=attempt, cmd=" ".join(cmd),
                        stderr=result.stderr.strip()[:200])
            time.sleep(backoff_s * attempt)
            continue
        break
    log.error("kubectl_failed", cmd=" ".join(cmd), stderr=last_stderr)
    raise RuntimeError(f"kubectl failed: {last_stderr}")


def apply_seed(
    meta: dict[str, object], manifests: list[dict[str, object]], seed: int
) -> None:
    old = int(meta.get("seed", 42))  # type: ignore[call-overload]
    meta["seed"] = seed
    sid = str(meta.get("scenario_id", ""))
    meta["scenario_id"] = f"{sid.removesuffix(f'-seed{old}')}-seed{seed}"
    for chaos in manifests:
        cmeta = chaos.setdefault("metadata", {})
        assert isinstance(cmeta, dict)
        name = str(cmeta.get("name", "fault"))
        cmeta["name"] = f"{name.removesuffix(f'-seed{old}')}-seed{seed}"


def inject(
    scenario_path: Path,
    dry_run: bool = False,
    seed: int | None = None,
    baseline_minutes: int = 30,
) -> None:
    meta, faults = parse_scenario(scenario_path)
    manifests = [manifest for _, manifest in faults]
    if seed is not None:
        apply_seed(meta, manifests, seed)

    scenario_id = str(meta.get("scenario_id", scenario_path.stem))
    fault_duration_s = int(meta.get("fault_duration_s", 300))   # default 5 min
    window_extra_s = int(meta.get("window_extra_s", 60))        # extra buffer around window
    namespace = str(meta.get("namespace", "otel-demo"))

    output_dir = _SNAPSHOTS_DIR / scenario_id
    # Start from a clean dir: reusing it mixes stale telemetry with fresh ground_truth
    # (the original cause of the 06-12 window vs 06-13 ground_truth inconsistency).
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("injecting_fault", scenario_id=scenario_id, fault_service=meta.get("fault_service"),
             fault_type=meta.get("fault_type"), dry_run=dry_run)

    injection_ts = datetime.now(UTC)
    snapshot_start = (injection_ts - timedelta(seconds=window_extra_s)).isoformat()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as tmp:
        yaml.safe_dump_all(manifests, tmp)
        tmp.flush()
        try:
            run_kubectl(["apply", "-f", tmp.name, "--validate=false"], dry_run=dry_run)
            if not dry_run:
                log.info("waiting_for_fault_duration", seconds=fault_duration_s)
                time.sleep(fault_duration_s)
        finally:
            run_kubectl(["delete", "-f", tmp.name, "--ignore-not-found"], dry_run=dry_run)

    recovery_ts = datetime.now(UTC)
    snapshot_end = (recovery_ts + timedelta(seconds=window_extra_s)).isoformat()

    truths = [
        extract_ground_truth(
            {**meta, **fault_meta, "scenario_id": scenario_id, "seed": meta.get("seed", 42)},
            chaos,
            injection_ts=injection_ts.isoformat(),
            recovery_ts=recovery_ts.isoformat(),
        )
        for fault_meta, chaos in faults
    ]
    gt = dict(truths[0])
    if len(truths) > 1:
        for key in ("fault_service", "fault_type", "chaos_kind", "chaos_manifest_hash"):
            del gt[key]
        gt["faults"] = truths
    if "split" in meta:
        gt["split"] = meta["split"]
    # Self-contained window so ground_truth and telemetry can never drift apart.
    gt["window_start"] = snapshot_start
    gt["window_end"] = snapshot_end

    # On a constrained host, resource-stress faults (cpu/memory) saturate the node so the
    # ~180-query snapshot burst, fired at peak load, OOM-crashes Prometheus and yields an empty
    # capture. Decouple the burst from peak stress: after recovery, let the node cool down, then
    # query. The fault-window data is already retained in Prometheus, so a later query still sees
    # the spike. Defaults to 0 (non-stress faults snapshot immediately, as before).
    # Never shorter than window_extra_s: the window ends window_extra_s after recovery, so
    # snapshotting earlier would miss the recovery tail.
    settle_s = max(int(meta.get("snapshot_settle_s", 0)), window_extra_s)
    if not dry_run and settle_s > 0:
        log.info("settling_before_snapshot", seconds=settle_s)
        time.sleep(settle_s)

    if not dry_run:
        log.info("snapshotting_telemetry", start=snapshot_start, end=snapshot_end)
        from scripts.snapshot_telemetry import snapshot
        snapshot(
            output_dir=output_dir,
            start=snapshot_start,
            end=snapshot_end,
            namespace=namespace,
            baseline_start=(
                injection_ts - timedelta(seconds=window_extra_s, minutes=baseline_minutes)
            ).isoformat(),
        )
        validation = [validate_snapshot(output_dir, truth) for truth in truths]
        gt["validation_passed"] = all(validation)
        for truth, passed in zip(truths, validation, strict=True):
            truth["validation_passed"] = passed

    # Written last, after validation, so ground_truth records whether the fault produced a
    # discriminative signal (the eval can flag/exclude snapshots that did not).
    with open(output_dir / "ground_truth.json", "w") as f:
        json.dump(gt, f, indent=2)
    log.info("ground_truth_written", path=str(output_dir / "ground_truth.json"),
             validation_passed=gt.get("validation_passed"))

    log.info("injection_complete", scenario_id=scenario_id, output_dir=str(output_dir))


def _series_mean(result: list) -> float | None:
    vals: list[float] = []
    for s in result:
        for _ts, v in s.get("values", []):
            try:
                f = float(v)
                if f == f:  # skip NaN
                    vals.append(f)
            except (ValueError, TypeError):
                pass
    return float(np.mean(vals)) if vals else None


def validate_snapshot(output_dir: Path, gt: dict[str, object]) -> bool:
    """Check that the capture contains the expected fault signal before using it in evaluation."""
    from src.datasources.live import ASTRONOMY_SHOP_SERVICES

    fault_service = str(gt.get("fault_service"))
    fault_type = str(gt.get("fault_type"))
    prom_path = output_dir / "prometheus" / "raw_queries.json"
    if not prom_path.exists():
        log.error("validate_no_prom_file", path=str(prom_path))
        return False

    entries = json.loads(prom_path.read_text())
    by_query: dict[str, list] = {
        str(e["query"]): e.get("result", []) for e in entries if not e.get("is_baseline")
    }
    baseline_by_query: dict[str, list] = {
        str(e["query"]): e.get("result", []) for e in entries if e.get("is_baseline")
    }

    if fault_type == "high_latency":
        return _validate_latency(fault_service, by_query, baseline_by_query)

    if fault_type == "http_abort":
        return _validate_abort(fault_service, by_query, baseline_by_query)

    if fault_type == "cpu_stress":
        return _validate_self_relative(
            fault_service, "cpu_stress", "cpu_usage", by_query, baseline_by_query,
            min_ratio=3.0, max_rank=3,
        )

    if fault_type == "memory_stress":
        if _validate_self_relative(
            fault_service, "memory_stress", "memory_usage", by_query, baseline_by_query,
            min_ratio=3.0, max_rank=3,
        ):
            return True
        return _validate_zscore_signal(fault_service, "memory_stress", "pod_restarts", by_query)

    best: dict[str, object] | None = None
    for sig in _FAULT_SIGNALS.get(fault_type, list(METRIC_QUERIES.keys())):
        tpl = METRIC_QUERIES[sig]
        svc_means: dict[str, float] = {}
        for svc in ASTRONOMY_SHOP_SERVICES:
            m = _series_mean(by_query.get(tpl.format(svc=svc), []))
            if m is not None:
                svc_means[svc] = m
        if fault_service not in svc_means or len(svc_means) < 3:
            continue
        vals = np.array(list(svc_means.values()))
        mu, sigma = float(vals.mean()), float(vals.std()) + 1e-9
        z = (svc_means[fault_service] - mu) / sigma
        rank = sorted(svc_means, key=lambda s: -abs((svc_means[s] - mu) / sigma)).index(
            fault_service
        ) + 1
        cand = {"signal": sig, "z": round(z, 2), "rank": rank,
                "fault_value": round(svc_means[fault_service], 4)}
        if best is None or abs(z) > abs(float(best["z"])):  # type: ignore[arg-type]
            best = cand
        if abs(z) >= 2.0 and rank <= 3:
            log.info("snapshot_validation_pass", service=fault_service,
                     fault_type=fault_type, **cand)
            return True

    log.warning("snapshot_validation_FAIL", service=fault_service, fault_type=fault_type,
                best=best, hint="faulted service is not a clear outlier; fault may not have fired")
    return False


def _validate_zscore_signal(
    fault_service: str,
    fault_type: str,
    signal: str,
    by_query: dict[str, list],
) -> bool:
    """Standard cross-service test: the faulted service is a |z|>=2 outlier ranked top-3 on a
    single signal. Used for pod_restarts (OOMKill / pod_crash), which IS a clean outlier."""
    from src.datasources.live import ASTRONOMY_SHOP_SERVICES

    tpl = METRIC_QUERIES[signal]
    svc_means: dict[str, float] = {}
    for svc in ASTRONOMY_SHOP_SERVICES:
        m = _series_mean(by_query.get(tpl.format(svc=svc), []))
        if m is not None:
            svc_means[svc] = m
    if fault_service not in svc_means or len(svc_means) < 3:
        log.warning("snapshot_validation_FAIL", service=fault_service, fault_type=fault_type,
                    best=None, hint=f"no {signal} for faulted service")
        return False
    vals = np.array(list(svc_means.values()))
    mu, sigma = float(vals.mean()), float(vals.std()) + 1e-9
    z = (svc_means[fault_service] - mu) / sigma
    rank = sorted(svc_means, key=lambda s: -abs((svc_means[s] - mu) / sigma)).index(
        fault_service) + 1
    cand = {"signal": signal, "z": round(z, 2), "rank": rank,
            "fault_value": round(svc_means[fault_service], 4)}
    if abs(z) >= 2.0 and rank <= 3:
        log.info("snapshot_validation_pass", service=fault_service, fault_type=fault_type, **cand)
        return True
    log.warning("snapshot_validation_FAIL", service=fault_service, fault_type=fault_type,
                best=cand, hint=f"{signal} not a |z|>=2 top-3 outlier")
    return False


def _validate_latency(
    fault_service: str,
    by_query: dict[str, list],
    baseline_by_query: dict[str, list],
) -> bool:
    """Validate relative latency growth rather than absolute latency, which includes callers."""
    from src.datasources.live import ASTRONOMY_SHOP_SERVICES

    tpl = METRIC_QUERIES["p99_latency_ms"]
    ratios: dict[str, float] = {}
    for svc in ASTRONOMY_SHOP_SERVICES:
        f = _series_mean(by_query.get(tpl.format(svc=svc), []))
        b = _series_mean(baseline_by_query.get(tpl.format(svc=svc), []))
        if f is not None and b and b > 0:
            ratios[svc] = f / b
    if fault_service not in ratios or len(ratios) < 3:
        log.warning("snapshot_validation_FAIL", service=fault_service, fault_type="high_latency",
                    best=None, hint="no p99 baseline+fault signal for faulted service")
        return False

    rank = sorted(ratios, key=lambda s: -ratios[s]).index(fault_service) + 1
    ratio = ratios[fault_service]
    fault_p99 = _series_mean(by_query.get(tpl.format(svc=fault_service), []))
    cand = {"signal": "p99_latency_ms", "rank_by_ratio": rank,
            "fault_value": round(fault_p99, 1) if fault_p99 else None,
            "fault_over_baseline": round(ratio, 2)}
    if rank <= 3 and ratio >= 3.0:
        log.info("snapshot_validation_pass", service=fault_service,
                 fault_type="high_latency", **cand)
        return True
    log.warning("snapshot_validation_FAIL", service=fault_service, fault_type="high_latency",
                best=cand, hint="culprit not top-3 by relative p99 jump or jump <3x its baseline")
    return False


def _validate_abort(
    fault_service: str,
    by_query: dict[str, list],
    baseline_by_query: dict[str, list],
) -> bool:
    """Gate for http_abort (NetworkChaos loss): the culprit's request_rate must have collapsed
    to <=50% of its OWN baseline. Dropped packets emit no error span (error_rate stays ~0) and
    the traffic collapse blends in with naturally-idle services, so a cross-service z-test
    cannot see it; the self-relative drop is the honest signal that the abort fired."""
    tpl = METRIC_QUERIES["request_rate"]
    fault_rate = _series_mean(by_query.get(tpl.format(svc=fault_service), []))
    base_rate = _series_mean(baseline_by_query.get(tpl.format(svc=fault_service), []))
    ratio = (
        (fault_rate / base_rate)
        if (base_rate and base_rate > 0 and fault_rate is not None)
        else None
    )
    cand = {"signal": "request_rate",
            "fault_value": round(fault_rate, 4) if fault_rate is not None else None,
            "baseline_value": round(base_rate, 4) if base_rate else None,
            "fault_over_baseline": round(ratio, 3) if ratio is not None else None}
    # Require a real baseline (the service was actually serving traffic before the fault) and a
    # >=50% collapse. Otherwise we cannot tell an abort from a naturally-idle service.
    if base_rate and base_rate > 0.005 and ratio is not None and ratio <= 0.5:
        log.info("snapshot_validation_pass", service=fault_service,
                 fault_type="http_abort", **cand)
        return True
    log.warning("snapshot_validation_FAIL", service=fault_service, fault_type="http_abort",
                best=cand,
                hint="culprit request_rate did not collapse to <=50% of its own baseline")
    return False


def _validate_self_relative(
    fault_service: str,
    fault_type: str,
    signal: str,
    by_query: dict[str, list],
    baseline_by_query: dict[str, list],
    min_ratio: float,
    max_rank: int,
) -> bool:
    """Gate for faults whose signal is pod-isolated but dominated by a steady-state heavy
    service (load-generator). PASS if the culprit's signal jumped >= min_ratio over its OWN
    baseline AND it ranks in the top-`max_rank` absolute consumers (the fault demonstrably
    fired and the culprit is among the loudest), rather than requiring a population z-outlier."""
    from src.datasources.live import ASTRONOMY_SHOP_SERVICES

    tpl = METRIC_QUERIES[signal]
    fault_means: dict[str, float] = {}
    for svc in ASTRONOMY_SHOP_SERVICES:
        m = _series_mean(by_query.get(tpl.format(svc=svc), []))
        if m is not None:
            fault_means[svc] = m
    if fault_service not in fault_means:
        log.warning("snapshot_validation_FAIL", service=fault_service, fault_type=fault_type,
                    best=None, hint=f"no {signal} for faulted service; fault may not have fired")
        return False

    rank = sorted(fault_means, key=lambda s: -fault_means[s]).index(fault_service) + 1
    fault_val = fault_means[fault_service]
    base_val = _series_mean(baseline_by_query.get(tpl.format(svc=fault_service), []))
    ratio = (fault_val / base_val) if base_val and base_val > 0 else float("inf")
    cand = {"signal": signal, "rank": rank, "fault_value": round(fault_val, 4),
            "baseline_value": round(base_val, 4) if base_val else None,
            "fault_over_baseline": round(ratio, 2) if ratio != float("inf") else "inf"}
    if ratio >= min_ratio and rank <= max_rank:
        log.info("snapshot_validation_pass", service=fault_service, fault_type=fault_type, **cand)
        return True
    log.warning("snapshot_validation_FAIL", service=fault_service, fault_type=fault_type,
                best=cand,
                hint=f"culprit {signal} not >={min_ratio}x its baseline or not top-{max_rank}")
    return False


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Inject Chaos Mesh fault + snapshot telemetry")
    parser.add_argument("--scenario", required=True, type=Path, help="Path to scenario YAML")
    parser.add_argument("--dry-run", action="store_true", help="Validate without injecting")
    parser.add_argument("--seed", type=int, default=None,
                        help="Override the scenario seed (replicate capture, own snapshot id)")
    parser.add_argument("--baseline-minutes", type=int, default=30,
                        help="Length of the pre-fault baseline window to capture")
    args = parser.parse_args()

    inject(args.scenario, dry_run=args.dry_run, seed=args.seed,
           baseline_minutes=args.baseline_minutes)


if __name__ == "__main__":
    main()
