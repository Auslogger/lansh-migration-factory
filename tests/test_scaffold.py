"""
The package, its CLI and the shared settings are wired up.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

import lansh
from lansh import config
from lansh.cli import app
from lansh.spark import get_spark, java_major_version

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


def test_cli_version() -> None:
    """
    The version command prints the package version.
    """
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert lansh.__version__ in result.output


def test_estate_generate_keeps_a_seed_of_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    ``--seed 0`` is a seed like any other; only leaving it out means the committed seed.
    """
    from lansh.estate import generate as gen

    seeds: dict[str, int] = {}

    def fake_generate(seed: int) -> dict[str, Any]:
        """
        Note the seed instead of generating the estate.
        """
        seeds["generate"] = seed
        return {}

    def fake_write(tables: dict[str, Any], *, seed: int, csv: bool) -> list[Any]:
        """
        Note the seed instead of writing any file.
        """
        seeds["write"] = seed
        return []

    monkeypatch.setattr(gen, "generate", fake_generate)
    monkeypatch.setattr(gen, "write", fake_write)
    for args, seed in (["--seed", "0"], 0), ([], gen.SEED):
        result = CliRunner().invoke(app, ["estate", "generate", *args])
        assert result.exit_code == 0, result.output
        assert seeds == {"generate": seed, "write": seed}


def test_repo_root_found() -> None:
    """
    The settings find this repository and its estate, and carry the plan's as-of date.
    """
    assert (config.REPO_ROOT / "pyproject.toml").exists()
    assert config.ESTATE_DIR == config.REPO_ROOT / "estate"
    assert config.AS_OF_DATE == "2025-12-31"


def test_java_major_version_reads_release_file(tmp_path: Path) -> None:
    (tmp_path / "release").write_text('IMPLEMENTOR="Homebrew"\nJAVA_VERSION="21.0.13"\n')
    assert java_major_version(tmp_path) == 21
    assert java_major_version(tmp_path / "missing") is None


@pytest.mark.parametrize(("version", "major"), [("1.8.0_392", 8), ("1.7.0", 7), ("17", 17)])
def test_java_major_version_reads_the_old_1_x_numbering(
    tmp_path: Path, version: str, major: int
) -> None:
    # Java 8 and older call themselves 1.8, 1.7, ...
    (tmp_path / "release").write_text(f'JAVA_VERSION="{version}"\n')
    assert java_major_version(tmp_path) == major


@pytest.mark.spark
def test_get_spark_returns_the_shared_session_unchanged(
    spark: SparkSession, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Settings apply when the session is created; a later call asking for others only warns.
    """
    app_name = spark.sparkContext.appName
    partitions = spark.conf.get("spark.sql.shuffle.partitions")
    assert partitions is not None
    with caplog.at_level(logging.WARNING, logger="lansh.spark"):
        assert get_spark(app_name, shuffle_partitions=int(partitions) + 4) is spark
    assert spark.conf.get("spark.sql.shuffle.partitions") == partitions
    assert "spark.sql.shuffle.partitions" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="lansh.spark"):
        assert get_spark(app_name, shuffle_partitions=int(partitions)) is spark
    assert not caplog.records


def test_env_example_lists_required_settings() -> None:
    text = (config.REPO_ROOT / "tests" / "fixtures" / ".env.example").read_text()
    assert "MSSQL_SA_PASSWORD=" in text


def test_secrets_and_exl_material_are_gitignored() -> None:
    """
    Git ignores secrets, the EXL deck and the lakehouse, however .gitignore spells the rules.
    """
    paths = [".env", ".authinfo", "docs/EXL_Trinity_Data_AI_Hackathon_2026.pptx", "lakehouse/x"]
    out = subprocess.run(
        ["git", "check-ignore", "--no-index", *paths],
        cwd=config.REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert sorted(out.stdout.split()) == sorted(paths)
