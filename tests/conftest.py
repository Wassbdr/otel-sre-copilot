"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.datasources.replay import ReplayDataSource

FIXTURE_SNAPSHOT = Path(__file__).parent / "fixtures" / "snapshot-fixture"


@pytest.fixture
def replay_ds() -> ReplayDataSource:
    """ReplayDataSource backed by the minimal fixture snapshot."""
    return ReplayDataSource(FIXTURE_SNAPSHOT)


@pytest.fixture
def fixture_snapshot_dir() -> Path:
    return FIXTURE_SNAPSHOT
