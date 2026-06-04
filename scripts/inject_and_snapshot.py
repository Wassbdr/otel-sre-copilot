"""Inject a Chaos Mesh fault, wait for recovery, then snapshot telemetry.

The scenario YAML has two sections:
1. metadata: scenario_id, fault_service, fault_type, seed, fault_duration, window_extra_s
2. chaos_manifest: the raw Chaos Mesh CRD YAML

The ground truth is extracted directly from the chaos_manifest (no human annotation).
CRD kind → fault_type mapping is a deterministic lookup table.

Usage:
    python scripts/inject_and_snapshot.py \\
        --scenario scenarios/mvp/001-checkoutservice-pod-crash.yaml \\
        [--dry-run]   # validate YAML without injecting
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

log = structlog.get_logger()

# Chaos Mesh CRD kind → fault_type mapping
_KIND_TO_FAULT_TYPE: dict[str, str] = {
    "PodChaos": "pod_crash",
    "NetworkChaos": "high_latency",
    "HTTPChaos": "http_abort",
    "StressChaos": "_stress",  # refined below by stressors field
    "DNSChaos": "high_latency",
    "IOChaos": "high_latency",
}

_SNAPSHOTS_DIR = Path("snapshots")


def parse_scenario(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    """Parse scenario YAML into (metadata, chaos_manifest)."""
    with open(path) as f:
        doc = yaml.safe_load(f)
    meta = doc.get("metadata", {})
    chaos = doc.get("chaos_manifest", {})
    if not meta or not chaos:
        raise ValueError(f"Scenario YAML must have 'metadata' and 'chaos_manifest' keys: {path}")
    return meta, chaos


def extract_ground_truth(
    meta: dict[str, object],
    chaos: dict[str, object],
    injection_ts: str,
    recovery_ts: str,
) -> dict[str, object]:
    """Build ground truth JSON from chaos manifest metadata (no human annotation)."""
    kind = str(chaos.get("kind", ""))
    fault_type = _KIND_TO_FAULT_TYPE.get(kind, "unknown")

    # Refine StressChaos: cpu vs memory
    if fault_type == "_stress":
        stressors = chaos.get("spec", {}).get("stressors", {})  # type: ignore[union-attr]
        if "cpu" in stressors:
            fault_type = "cpu_stress"
        elif "memory" in stressors:
            fault_type = "memory_stress"
        else:
            fault_type = "cpu_stress"  # default

    # Extract affected service from label selector
    selector = (
        chaos.get("spec", {}).get("selector", {}).get("labelSelectors", {})  # type: ignore[union-attr]
        or {}
    )
    fault_service = str(meta.get("fault_service", selector.get("app", "unknown")))

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


def run_kubectl(args: list[str], dry_run: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = ["kubectl"] + args
    if dry_run:
        log.info("dry_run_kubectl", cmd=" ".join(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("kubectl_failed", cmd=" ".join(cmd), stderr=result.stderr)
        raise RuntimeError(f"kubectl failed: {result.stderr}")
    return result


def inject(
    scenario_path: Path,
    dry_run: bool = False,
) -> None:
    meta, chaos = parse_scenario(scenario_path)

    scenario_id = str(meta.get("scenario_id", scenario_path.stem))
    fault_duration_s = int(meta.get("fault_duration_s", 300))   # default 5 min
    window_extra_s = int(meta.get("window_extra_s", 60))        # extra buffer around window
    namespace = str(meta.get("namespace", "otel-demo"))

    output_dir = _SNAPSHOTS_DIR / scenario_id
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("injecting_fault", scenario_id=scenario_id, fault_service=meta.get("fault_service"),
             fault_type=meta.get("fault_type"), dry_run=dry_run)

    injection_ts = datetime.now(timezone.utc)
    snapshot_start = (injection_ts - timedelta(seconds=window_extra_s)).isoformat()

    # Write chaos manifest to temp file and apply via kubectl
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        yaml.dump(chaos, tmp)
        tmp_path = tmp.name

    run_kubectl(["apply", "-f", tmp_path], dry_run=dry_run)
    Path(tmp_path).unlink(missing_ok=True)

    if not dry_run:
        log.info("waiting_for_fault_duration", seconds=fault_duration_s)
        time.sleep(fault_duration_s)

    # Delete the chaos resource to trigger recovery
    chaos_name = str(chaos.get("metadata", {}).get("name", ""))  # type: ignore[union-attr]
    chaos_kind = str(chaos.get("kind", ""))
    chaos_ns = str(chaos.get("metadata", {}).get("namespace", "chaos-mesh"))  # type: ignore[union-attr]
    run_kubectl(
        ["delete", chaos_kind, chaos_name, "-n", chaos_ns, "--ignore-not-found"],
        dry_run=dry_run,
    )

    recovery_ts = datetime.now(timezone.utc)
    snapshot_end = (recovery_ts + timedelta(seconds=window_extra_s)).isoformat()

    # Write ground truth
    gt = extract_ground_truth(
        meta, chaos,
        injection_ts=injection_ts.isoformat(),
        recovery_ts=recovery_ts.isoformat(),
    )
    with open(output_dir / "ground_truth.json", "w") as f:
        json.dump(gt, f, indent=2)
    log.info("ground_truth_written", path=str(output_dir / "ground_truth.json"))

    if not dry_run:
        log.info("snapshotting_telemetry", start=snapshot_start, end=snapshot_end)
        from scripts.snapshot_telemetry import snapshot
        snapshot(
            output_dir=output_dir,
            start=snapshot_start,
            end=snapshot_end,
            namespace=namespace,
        )

    log.info("injection_complete", scenario_id=scenario_id, output_dir=str(output_dir))


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Inject Chaos Mesh fault + snapshot telemetry")
    parser.add_argument("--scenario", required=True, type=Path, help="Path to scenario YAML")
    parser.add_argument("--dry-run", action="store_true", help="Validate without injecting")
    args = parser.parse_args()

    inject(args.scenario, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
