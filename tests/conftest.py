"""
Shared fixtures: one Spark session for every suite, and Claude kept in replay mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lansh.config import load_env

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


@pytest.fixture(autouse=True)
def _claude_replays_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep Claude in replay mode, so no test makes a live call unless it passes mode='live'.

    ``.env`` is loaded first so that a developer's ``LANSH_LLM_MODE=auto`` can't leak in.
    """
    load_env()
    monkeypatch.setenv("LANSH_LLM_MODE", "replay")


@pytest.fixture(scope="session")
def spark() -> SparkSession:
    """
    Share one local Spark session (Delta, UTC, ANSI on) across the whole test run.
    """
    from lansh.spark import get_spark

    return get_spark("lansh-tests")
