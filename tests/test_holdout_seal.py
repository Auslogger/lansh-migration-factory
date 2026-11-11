"""
The held-out seal is reproducible, detects tampering, and factory code can't see the answers.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from lansh.config import REPO_ROOT
from lansh.estate import holdout

### The seal


def _folder(tmp_path: Path) -> Path:
    """
    Make a small folder to seal, with a nested file and some non-ASCII text.
    """
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "X1_job.sql").write_text("SELECT 1;\n")
    (src / "sub" / "notes.md").write_text("Seán\n")
    return src


def test_packing_is_byte_reproducible(tmp_path: Path) -> None:
    src = _folder(tmp_path)
    first = holdout.pack(src)
    (src / "X1_job.sql").touch()  # a newer mtime must not change the archive
    assert holdout.pack(src) == first


def test_seal_verify_and_tamper_detection(tmp_path: Path) -> None:
    src, out = _folder(tmp_path), tmp_path / "sealed"
    record = holdout.seal(src, out)
    assert record["files"] == ["X1_job.sql", "sub/notes.md"]
    assert holdout.verify_seal(out)
    with pytest.raises(FileExistsError):
        holdout.seal(src, out)
    archive = out / holdout.ARCHIVE
    archive.write_bytes(archive.read_bytes() + b"\0")
    assert not holdout.verify_seal(out)


def test_unseal_round_trip(tmp_path: Path) -> None:
    src, out = _folder(tmp_path), tmp_path / "sealed"
    holdout.seal(src, out)
    names = holdout.unseal(tmp_path / "opened", out)
    assert sorted(names) == ["X1_job.sql", "sub/notes.md"]
    assert (tmp_path / "opened" / "sub" / "notes.md").read_text() == "Seán\n"


### Factory isolation

# evaluation and estate tooling may read the answer key; the factory may not
ALLOWED = {"config.py", "estate"}
SEALED_FOLDERS = {"labels", "holdout"}
SEALED_MODULES = {"lansh.estate.labels", "lansh.estate.holdout"}
# the folder constants, and the estate functions that read the answer key or the sealed
# archive, so factory code can't reach either through them
SEALED_NAMES = {"LABELS_DIR", "HOLDOUT_DIR", "run_tsql_checks", "run_sas_checks", "unseal"}
# a path or module name leading into either folder, or the name of either folder's constant
SEALED_TEXT = re.compile(r"estate[/\\.](?:labels|holdout)|LABELS_DIR|HOLDOUT_DIR")
# calls that build a path from parts, besides the / operator
PATH_BUILDERS = {"joinpath", "Path", "PurePath"}


def _is_sealed_module(name: str) -> bool:
    """
    Tell whether a dotted module name is a sealed module, or inside one.
    """
    return any(name == sealed or name.startswith(sealed + ".") for sealed in SEALED_MODULES)


def _absolute_module(module: str | None, level: int, package: str) -> str:
    """
    Resolve the module of a ``from ... import`` to its absolute name.

    ``level`` counts the leading dots: one is ``package`` itself, two its parent, and so on.
    """
    if not level:
        return module or ""
    parts = package.split(".")
    base = parts[: max(0, len(parts) - level + 1)]
    return ".".join([*base, module] if module else base)


def _last_name(node: ast.AST) -> str:
    """
    Give the last part of a dotted name: ``estate`` for ``lansh.estate``; empty for others.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_sealed_part(node: ast.AST) -> bool:
    """
    Tell whether ``node`` is a string with ``labels`` or ``holdout`` among its path parts.
    """
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and not SEALED_FOLDERS.isdisjoint(re.split(r"[/\\]", node.value))
    )


def _builds_sealed_path(node: ast.AST) -> bool:
    """
    Tell whether ``node`` builds a path with a ``labels`` or ``holdout`` part.

    That is ``/`` with such a string on either side, or ``Path()``, ``joinpath()`` or
    ``os.path.join()`` with one among its arguments. A ``join`` on anything but ``path``
    (``str.join``, a DataFrame join) doesn't count.
    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_sealed_part(node.left) or _is_sealed_part(node.right)
    if isinstance(node, ast.Call):
        name = _last_name(node.func)
        on_path = isinstance(node.func, ast.Attribute) and _last_name(node.func.value) == "path"
        if name in PATH_BUILDERS or (name == "join" and on_path):
            return any(_is_sealed_part(arg) for arg in node.args)
    return False


def sealed_references(source: str, package: str) -> list[str]:
    """
    Find every place where a module's code reaches the answer key or the held-out jobs.

    It flags an import of ``lansh.estate.labels`` or ``lansh.estate.holdout`` in any form
    (absolute, ``from ... import``, aliased or relative, and ``import *`` from
    ``lansh.estate``), the names ``LABELS_DIR`` and ``HOLDOUT_DIR``, the dotted names
    ``estate.labels`` and ``estate.holdout``, a path built with a ``labels`` or ``holdout``
    part (``ESTATE_DIR / "labels"``, ``joinpath``, ``os.path.join``, ``Path()``), and any
    string naming one of the folders, modules or constants, which covers ``importlib`` and
    ``getattr``. A string that stands alone as a statement, such as a docstring, is never
    read, so it may mention them. Comments are not code, so they may too.

    Args:
        source: The module's source code.
        package: The package the module is in, such as ``lansh.engines``; relative imports
            resolve against it.

    Returns:
        One ``line N: what`` entry per finding, in line order; empty for a clean module.
    """
    tree = ast.parse(source)
    inert = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_sealed_module(alias.name):
                    found.append((line, f"imports {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            module = _absolute_module(node.module, node.level, package)
            for alias in node.names:
                if _is_sealed_module(module) or _is_sealed_module(f"{module}.{alias.name}"):
                    found.append((line, f"imports {module}.{alias.name}"))
                elif alias.name == "*" and module == "lansh.estate":
                    # a star import picks up every submodule imported so far, labels included
                    found.append((line, "imports * from lansh.estate"))
                elif alias.name in SEALED_NAMES:
                    found.append((line, f"imports {alias.name}"))
        elif isinstance(node, ast.Name) and node.id in SEALED_NAMES:
            found.append((line, f"uses {node.id}"))
        elif isinstance(node, ast.Attribute) and (
            node.attr in SEALED_NAMES
            or (node.attr in SEALED_FOLDERS and _last_name(node.value) == "estate")
        ):
            found.append((line, f"uses {_last_name(node.value)}.{node.attr}"))
        elif _builds_sealed_path(node):
            found.append((line, "builds a path into a sealed folder"))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in inert
            and SEALED_TEXT.search(node.value)
        ):
            found.append((line, f"names {node.value!r}"))
    return [f"line {line}: {what}" for line, what in sorted(found)]


@pytest.mark.parametrize(
    ("source", "package"),
    [
        pytest.param("import lansh.estate.labels", "lansh", id="import"),
        pytest.param("import lansh.estate.holdout as sealed", "lansh", id="aliased import"),
        pytest.param("from lansh.estate import golden, labels", "lansh", id="from-import"),
        pytest.param(
            "from lansh.estate import (\n    golden,\n    holdout,\n)", "lansh", id="multi-line"
        ),
        pytest.param("from lansh.estate import labels as key", "lansh", id="aliased from-import"),
        pytest.param("from lansh.estate.labels import load_label", "lansh", id="from the module"),
        pytest.param("from lansh.estate import *", "lansh", id="star import"),
        pytest.param("from ..estate import holdout", "lansh.engines", id="relative"),
        pytest.param("from ..estate.labels import CheckResult", "lansh.llm", id="relative module"),
        pytest.param("from .estate import labels", "lansh", id="relative from the top"),
        pytest.param("from lansh.config import LABELS_DIR", "lansh", id="folder constant"),
        pytest.param("from lansh import config\nconfig.HOLDOUT_DIR", "lansh", id="as attribute"),
        pytest.param("import lansh.estate\nlansh.estate.labels.CHECK_ID", "lansh", id="dotted"),
        pytest.param("key = ESTATE_DIR / 'labels'", "lansh", id="path join"),
        pytest.param("tar = ESTATE_DIR / 'holdout' / 'sealed.tar'", "lansh", id="longer join"),
        pytest.param("key = ESTATE_DIR / 'labels/T01.yaml'", "lansh", id="join with a subpath"),
        pytest.param("key = ESTATE_DIR.joinpath('labels', 'T01.yaml')", "lansh", id="joinpath"),
        pytest.param("import os\nos.path.join(ESTATE_DIR, 'holdout')", "lansh", id="os.path"),
        pytest.param("key = Path(ESTATE_DIR, 'labels')", "lansh", id="Path()"),
        pytest.param("open('estate/labels/T01.yaml')", "lansh", id="path string"),
        pytest.param(
            "import importlib\nimportlib.import_module('lansh.estate.holdout')",
            "lansh",
            id="importlib",
        ),
        pytest.param("folder = getattr(config, 'LABELS_DIR')", "lansh", id="getattr"),
        pytest.param("from lansh.estate.runner import run_tsql_checks", "lansh", id="check runner"),
        pytest.param(
            "from lansh.estate import golden_sas\ngolden_sas.run_sas_checks('S01')",
            "lansh",
            id="check runner by attribute",
        ),
    ],
)
def test_isolation_check_catches(source: str, package: str) -> None:
    assert sealed_references(source, package), source


HARMLESS = '''\
"""
Reads the inventory and golden outputs, never estate/labels/ or estate/holdout/.
"""

import os

from lansh.config import ESTATE_DIR, GOLDEN_DIR
from lansh.estate import golden, inventory

from ..estate import fingerprint

labels = ["semantic", "construct"]  # a list called labels is fine


def manifest(job, row, df, other):
    """
    The job's golden manifest. A docstring may name lansh.estate.labels and LABELS_DIR.
    """
    flagged = job.holdout and row["labels"]
    df.join(other, "labels")  # a DataFrame join, not a path
    os.path.join(ESTATE_DIR, "jobs.yaml")
    return GOLDEN_DIR / job.job_id / "manifest.json", flagged
'''


def test_isolation_check_passes_a_harmless_module() -> None:
    assert sealed_references(HARMLESS, "lansh.engines") == []


def test_factory_code_never_reads_labels_or_holdout() -> None:
    src = REPO_ROOT / "src" / "lansh"
    checked, offenders = [], []
    for path in sorted(src.rglob("*.py")):
        if path.relative_to(src).parts[0] in ALLOWED:
            continue
        checked.append(path)
        # the package a module is in: lansh.engines for engines/sas.py and engines/__init__.py
        package = ".".join(path.relative_to(REPO_ROOT / "src").parts[:-1])
        found = sealed_references(path.read_text(encoding="utf-8"), package)
        offenders += [f"{path.relative_to(REPO_ROOT)} {what}" for what in found]
    assert src / "cli.py" in checked
    assert offenders == []
