"""
Refresh the package table in THIRD_PARTY.md from installed package metadata.

Run with ``make third-party``. Only the table between the ``<!-- packages:start -->`` and
``<!-- packages:end -->`` markers is rewritten; the services, run-time downloads and data
sections around it are maintained by hand. A licence the metadata leaves unclear is listed
for a manual check rather than guessed.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "THIRD_PARTY.md"
START, END = "<!-- packages:start -->", "<!-- packages:end -->"


def _requirement_names(pyproject: dict) -> list[tuple[str, str]]:
    """
    List the direct dependencies declared in pyproject.toml.

    Args:
        pyproject: The parsed pyproject.toml.

    Returns:
        (package name, "runtime" or "dev") pairs, runtime dependencies first.
    """

    def name(req: str) -> str:
        """
        Take the bare package name from a requirement string.
        """
        # a requirement such as "pandas>=2.3,<3" or "saspy[iom]" starts with the bare name
        return re.split(r"[<>=!~\[ ;]", req, maxsplit=1)[0]

    runtime = [(name(r), "runtime") for r in pyproject["project"]["dependencies"]]
    dev = [(name(r), "dev") for r in pyproject.get("dependency-groups", {}).get("dev", [])]
    return runtime + dev


def _licence(dist: md.Distribution) -> str:
    """
    Name an installed package's licence from its metadata.

    Tries, in order, the SPDX ``License-Expression``, the ``License ::`` classifiers and a
    short ``License`` field.

    Args:
        dist: The installed distribution.

    Returns:
        The licence name, or a note asking for a manual check.
    """
    meta = dist.metadata
    expr = meta.get("License-Expression")
    if expr:
        return expr
    classifiers = [
        c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(dict.fromkeys(classifiers))
    text = (meta.get("License") or "").strip()
    if text and len(text) < 60 and "\n" not in text:
        return text
    # some packages paste the whole licence text into the metadata; name the well-known ones
    head = text[:200].upper()
    if "GNU LESSER GENERAL PUBLIC LICENSE" in head and "2.1" in head:
        return "LGPL-2.1"
    return "see package (check manually)"


def package_table(pyproject: dict) -> str:
    """
    Build the Markdown table of direct dependencies with their versions and licences.

    Args:
        pyproject: The parsed pyproject.toml.

    Returns:
        The table, header included, without a trailing newline.
    """
    rows = []
    for pkg, group in _requirement_names(pyproject):
        try:
            dist = md.distribution(pkg)
            rows.append((pkg, dist.version, _licence(dist), group))
        except md.PackageNotFoundError:
            rows.append((pkg, "not installed", "unknown", group))
    lines = ["| Package | Version | Licence | Used for |", "|---|---|---|---|"]
    for pkg, version, licence, group in sorted(rows, key=lambda r: r[0].lower()):
        lines.append(f"| {pkg} | {version} | {licence} | {group} |")
    return "\n".join(lines)


def main() -> None:
    """
    Rewrite the table between the markers in THIRD_PARTY.md, leaving the rest untouched.

    Raises:
        SystemExit: If either marker is missing.
    """
    text = TARGET.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit(f"{TARGET.name} has lost its {START} / {END} markers")
    before, rest = text.split(START, 1)
    _old, after = rest.split(END, 1)
    table = package_table(tomllib.loads((ROOT / "pyproject.toml").read_text()))
    TARGET.write_text(f"{before}{START}\n{table}\n{END}{after}", encoding="utf-8")
    print(f"updated {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
