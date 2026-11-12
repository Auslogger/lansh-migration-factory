"""
Repository paths and environment settings shared by every LANSH module.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

from dotenv import load_dotenv

# the reporting date every legacy job and every migrated job runs as of
AS_OF_DATE = "2025-12-31"
# the SQL Server database that holds the legacy estate
LEGACY_DATABASE = "SynthInsureDW"


def _find_repo_root() -> Path:
    """
    Find the repository root by walking up from this file.

    The root is the nearest parent holding both ``pyproject.toml`` and ``src/lansh``.
    Outside a checkout, such as in a non-editable install, it is the working directory.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "src" / "lansh").is_dir():
            return parent
    return Path.cwd()


REPO_ROOT = _find_repo_root()
ESTATE_DIR = REPO_ROOT / "estate"
DATA_DIR = ESTATE_DIR / "data"
TSQL_DIR = ESTATE_DIR / "tsql"
SAS_DIR = ESTATE_DIR / "sas"
GOLDEN_DIR = ESTATE_DIR / "golden"
# sealed held-out jobs. Factory code must never read this folder
HOLDOUT_DIR = ESTATE_DIR / "holdout"
# the answer key. Only evaluation code may read this folder
LABELS_DIR = ESTATE_DIR / "labels"
INVENTORY_PATH = ESTATE_DIR / "jobs.yaml"
RUNS_DIR = REPO_ROOT / "runs"
LAKEHOUSE_DIR = REPO_ROOT / "lakehouse"


@cache
def load_env() -> None:
    """
    Load ``.env`` from the repository root, once.

    Variables already set in the environment win over the file. A missing file is fine.
    """
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)


def env(name: str, default: str | None = None) -> str | None:
    """
    Read a setting from the environment, after loading ``.env``.

    An empty value counts as unset, so ``NAME=`` in ``.env`` gives the default.

    Args:
        name: Variable name, such as ``MSSQL_SA_PASSWORD``.
        default: Value to return when the variable is unset or empty.

    Returns:
        The variable's value, or ``default``.
    """
    load_env()
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def require_env(name: str) -> str:
    """
    Read a required setting, failing with a pointer to ``tests/fixtures/.env.example``.

    Args:
        name: Variable name, such as ``MSSQL_SA_PASSWORD``.

    Returns:
        The variable's value, which is never empty.

    Raises:
        RuntimeError: If the variable is unset or empty.
    """
    value = env(name)
    if value is None:
        raise RuntimeError(
            f"{name} is not set. Copy tests/fixtures/.env.example to .env and fill it in."
        )
    return value
