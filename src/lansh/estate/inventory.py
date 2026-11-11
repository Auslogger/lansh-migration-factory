"""
Read and write ``estate/jobs.yaml``, the legacy estate inventory.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from lansh.config import INVENTORY_PATH
from lansh.contracts import EstateInventory


class _PlainLoader(yaml.SafeLoader):
    """
    A SafeLoader without YAML 1.1's surprises.

    ISO dates stay text, because job parameters are strings. Only true and false are
    booleans, not yes/no/on/off, so a country code NO stays 'NO'. Numbers are plain
    decimals: no sexagesimal (1:30 == 90) and no octal (010 == 8).
    """


_DROPPED = {
    "tag:yaml.org,2002:timestamp",
    "tag:yaml.org,2002:bool",
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
}
"""Tags taken out of SafeLoader's implicit resolvers; bool, int and float come back stricter."""

_PlainLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag not in _DROPPED]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_PlainLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)
_PlainLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int", re.compile(r"^[-+]?(?:0|[1-9][0-9]*)$"), list("-+0123456789")
)
_PlainLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?$"),
    list("-+0123456789."),
)


def parse_yaml(text: str) -> Any:
    """
    Parse YAML with plain types: no dates, YAML 1.1 booleans or sexagesimal numbers.

    Args:
        text: A YAML document.

    Returns:
        The document as dicts, lists, strings, numbers, booleans and None.
    """
    return yaml.load(text, Loader=_PlainLoader)


def load_inventory(path: Path = INVENTORY_PATH) -> EstateInventory:
    """
    Load and validate the inventory.

    Args:
        path: The inventory's YAML file.

    Returns:
        The validated inventory.

    Raises:
        pydantic.ValidationError: The file doesn't match :class:`EstateInventory`.
    """
    return EstateInventory.model_validate(parse_yaml(Path(path).read_text(encoding="utf-8")))


def dump_inventory(inventory: EstateInventory) -> str:
    """
    Serialise the inventory to YAML in field order.

    Defaults are left out, but ``version`` is always written, and first.

    Args:
        inventory: The inventory to serialise.

    Returns:
        The YAML text.
    """
    data = inventory.model_dump(mode="json", exclude_defaults=True)
    data = {"version": inventory.version, **data}
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
