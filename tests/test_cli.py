import json
from pathlib import Path

import pytest

from src.api import InvestigationError, investigate_snapshot
from src.cli import main

SNAPSHOT = Path(__file__).parents[1] / "snapshots/checkout-pod_crash-seed42"


def test_cli_snapshot_writes_json_without_logs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    main(["investigate", "--snapshot", str(SNAPSHOT)])
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["incident_id"] == "snapshot"
    assert report["root_causes"]
    assert report["grounding_score"] == 1.0


def test_cli_live_requires_both_timestamps(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["investigate", "--live"])
    assert error.value.code == 2
    assert "--live requires --start and --end." in capsys.readouterr().err


def test_snapshot_boundary_explains_required_files(tmp_path: Path) -> None:
    with pytest.raises(InvestigationError, match="metadata.json.*window_start"):
        investigate_snapshot(tmp_path)
