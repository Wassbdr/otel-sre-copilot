"""Command line interface for OTel SRE-Copilot."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import structlog
from dotenv import load_dotenv

from src.api import InvestigationError, investigate_live, investigate_snapshot


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    config = structlog.get_config()
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
    try:
        _run(argv)
    finally:
        structlog.configure(**config)


def _run(argv: list[str] | None) -> None:
    parser = argparse.ArgumentParser(prog="copilot", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    investigate = commands.add_parser("investigate", help="Investigate a snapshot or live window.")
    mode = investigate.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshot", type=Path)
    mode.add_argument("--live", action="store_true")
    investigate.add_argument("--incident-id")
    investigate.add_argument("--start", help="ISO 8601 timestamp with timezone for live mode.")
    investigate.add_argument("--end", help="ISO 8601 timestamp with timezone for live mode.")
    investigate.add_argument("--namespace")
    investigate.add_argument("--service", action="append", help="Live service name; repeat to add.")
    investigate.add_argument("--output", type=Path, help="Write JSON here instead of stdout.")
    args = parser.parse_args(argv)
    if args.live and (not args.start or not args.end):
        investigate.error("--live requires --start and --end.")
    if args.snapshot and any((args.start, args.end, args.namespace, args.service)):
        investigate.error("--snapshot takes its window, namespace and services from metadata.json.")
    try:
        if args.snapshot:
            report = investigate_snapshot(args.snapshot, incident_id=args.incident_id or "snapshot")
        else:
            try:
                start, end = datetime.fromisoformat(args.start), datetime.fromisoformat(args.end)
            except ValueError as error:
                raise InvestigationError(
                    "Use an ISO 8601 timestamp with timezone, such as 2026-01-15T14:00:00Z."
                ) from error
            report = investigate_live(
                start=start, end=end, incident_id=args.incident_id or "incident",
                namespace=args.namespace or os.getenv("K8S_NAMESPACE", "otel-demo"),
                services=args.service,
            )
        payload = report.model_dump_json(indent=2) + "\n"
        if args.output:
            args.output.write_text(payload)
        else:
            sys.stdout.write(payload)
    except InvestigationError as error:
        investigate.exit(1, f"copilot: {error}\n")
    except OSError as error:
        investigate.exit(1, f"copilot: Cannot write the report. Check --output: {error}\n")


if __name__ == "__main__":
    main()
