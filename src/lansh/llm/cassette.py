"""
Recorded Claude answers ("cassettes"): one JSON file per request hash (plan §8.2).

A cassette holds the request (prompts, schema and flags, never the binary path or the
environment), the validated ``structured_output``, the call's ``usage``, ``modelUsage``,
``total_cost_usd`` and ``duration_ms``, the CLI version and when it was recorded.

Cassettes are committed (``runs/cassettes/`` is tracked), so ``save`` scrubs them first: the
value of any secret-looking environment variable, the repository path and the home directory
never reach disk.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lansh.config import REPO_ROOT, RUNS_DIR, load_env
from lansh.contracts import Sha256
from lansh.llm.errors import CassetteInvalidError, CassetteSafetyError

log = logging.getLogger(__name__)

DEFAULT_CASSETTE_DIR = RUNS_DIR / "cassettes"

# stand-ins for the two long flag values in a recorded command line; the values themselves
# are recorded once, in the request
SYSTEM_PROMPT_PLACEHOLDER = "<system_prompt>"
JSON_SCHEMA_PLACEHOLDER = "<json_schema>"

# variables named like this hold secrets, whose values are scrubbed; values shorter than
# _MIN_SECRET_LENGTH are skipped, so that something like "1" isn't replaced all over a cassette
_SECRET_NAME = re.compile(r"PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|CREDENTIAL", re.IGNORECASE)
_MIN_SECRET_LENGTH = 8


class _Record(BaseModel):
    """
    Base for the cassette models: unknown keys are an error, and aliased fields load by name too.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RecordedRequest(_Record):
    """
    The request as sent, minus anything machine-specific.

    After a retry it still holds the original prompt, the one a replay will be asked for.

    Attributes:
        agent: The agent that made the call; a label, not part of the request hash.
        job_id: The job the call was about, if any; also only a label.
        model: The ``--model`` alias.
        effort: The ``--effort`` level.
        system_prompt: The system prompt, kept here rather than in ``flags``.
        prompt: The prompt, which was sent on stdin.
        json_schema: The response model's JSON schema, kept here rather than in ``flags``.
        flags: The arguments after the binary, with ``<system_prompt>`` and ``<json_schema>``
            in place of those two values.
    """

    agent: str
    job_id: str | None = None
    model: str
    effort: str
    system_prompt: str
    prompt: str
    json_schema: dict[str, Any]
    flags: list[str] = Field(
        description="The command line after the binary, with placeholders for the system "
        "prompt and the JSON schema. The prompt is never on it: it goes on stdin."
    )


class RecordedResponse(_Record):
    """
    The parts of the result envelope worth keeping.

    Attributes:
        structured_output: The answer, which also passed the response model's validation.
        usage: The envelope's ``usage``, summed over all turns of the call.
        model_usage: The envelope's ``modelUsage``: tokens and cost for each model that
            answered. Written to disk as ``modelUsage``.
        total_cost_usd: What the call would cost on the API, in US dollars; nothing is billed.
        duration_ms: How long the call took as the CLI measured it, start-up excluded.
        duration_api_ms: How much of that was spent on API requests, when reported.
        num_turns: Turns the call took, when reported; a structured answer takes 2.
        envelope_keys: The envelope's top-level keys, which show if the CLI's format changes.
    """

    structured_output: dict[str, Any]
    usage: dict[str, Any]
    model_usage: dict[str, Any] = Field(alias="modelUsage")
    total_cost_usd: float
    duration_ms: int
    duration_api_ms: int | None = None
    num_turns: int | None = None
    envelope_keys: list[str] = Field(default_factory=list)


class Cassette(_Record):
    """
    One recorded answer, keyed by its request hash.

    Attributes:
        format_version: The cassette layout; 1 is the only one so far.
        request_sha256: The request hash, which is also the file name.
        request: What was sent.
        response: What came back.
        attempts: Live calls it took to get a valid answer; 2 after a retry.
        retry_reason: Why the first answer was rejected, when there was a retry.
        cli_version: The Claude Code version that answered.
        recorded_at: When the answer was recorded.
    """

    format_version: Literal[1] = 1
    request_sha256: Sha256
    request: RecordedRequest
    response: RecordedResponse
    attempts: int = Field(default=1, ge=1, description="Live calls it took to get a valid answer.")
    retry_reason: str | None = None
    cli_version: str
    recorded_at: datetime


def recorded_flags(flags: list[str]) -> list[str]:
    """
    Replace the system prompt and JSON schema values in a command line with placeholders.

    Args:
        flags: The arguments after the binary, as ``build_flags`` returns them.

    Returns:
        A copy of ``flags`` with ``<system_prompt>`` and ``<json_schema>`` in place of the
        two values; a flag that has no value after it is left alone.
    """
    out = list(flags)
    for flag, placeholder in (
        ("--system-prompt", SYSTEM_PROMPT_PLACEHOLDER),
        ("--json-schema", JSON_SCHEMA_PLACEHOLDER),
    ):
        if flag in out[:-1]:
            out[out.index(flag) + 1] = placeholder
    return out


def _secret_values() -> list[tuple[str, str]]:
    """
    List the environment variables that look like secrets, with their values.

    Returns:
        (name, value) pairs for each variable named like a secret whose value is long enough
        to scrub.
    """
    load_env()  # so secrets kept only in .env are known too
    return [
        (name, value)
        for name, value in os.environ.items()
        if _SECRET_NAME.search(name) and len(value) >= _MIN_SECRET_LENGTH
    ]


def scrub(text: str) -> tuple[str, list[str]]:
    """
    Remove secret values, the repository path and the home directory from ``text``.

    Each secret is looked for as it is and JSON-escaped, since ``text`` is normally a
    cassette's JSON: escaped as ``save`` writes it, with non-ASCII text kept, and with
    non-ASCII text escaped too. The longest form is replaced first, so a shorter one can't
    split it. The repository path is replaced before the home directory that usually
    contains it, and a path of just ``/`` is left alone.

    Args:
        text: The text to scrub, normally a cassette's JSON.

    Returns:
        The scrubbed text, and what was removed: the names of the secret variables (never
        their values), plus ``<repo>`` or ``~`` for each path replaced.
    """
    removed: list[str] = []
    for name, value in _secret_values():
        forms = {value, json.dumps(value, ensure_ascii=False)[1:-1], json.dumps(value)[1:-1]}
        for form in sorted(forms, key=lambda f: (-len(f), f)):
            if form in text:
                text = text.replace(form, f"<redacted:{name}>")
                removed.append(name)
    for path, replacement in ((str(REPO_ROOT), "<repo>"), (str(Path.home()), "~")):
        if len(path) > 1 and path in text:
            text = text.replace(path, replacement)
            removed.append(replacement)
    return text, sorted(set(removed))


class CassetteStore:
    """
    A folder of cassettes, one ``<request_sha256>.json`` file each.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        """
        Point a store at a folder; it is created on the first save.

        Args:
            root: The folder to use; ``runs/cassettes/`` when not given.
        """
        self.root = Path(root) if root is not None else DEFAULT_CASSETTE_DIR

    def path_for(self, request_sha256: str) -> Path:
        """
        Name the file that holds, or would hold, a request's cassette.

        Args:
            request_sha256: The hash from ``ClaudeRequest.request_sha256``.

        Returns:
            ``<root>/<request_sha256>.json``, whether or not it exists.
        """
        return self.root / f"{request_sha256}.json"

    def load(self, request_sha256: str) -> Cassette | None:
        """
        Read the cassette recorded for a request.

        Args:
            request_sha256: The hash from ``ClaudeRequest.request_sha256``.

        Returns:
            The cassette, or None when none is recorded.

        Raises:
            CassetteInvalidError: If the file isn't a valid cassette, or records a different
                request hash from the one in its name.
        """
        path = self.path_for(request_sha256)
        if not path.is_file():
            return None
        try:
            cassette = Cassette.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise CassetteInvalidError(
                f"{path.name} is not a valid cassette ({exc.error_count()} problems)"
            ) from exc
        if cassette.request_sha256 != request_sha256:
            raise CassetteInvalidError(f"{path.name} records request {cassette.request_sha256}")
        return cassette

    def save(self, cassette: Cassette) -> Path:
        """
        Scrub a cassette and write it atomically, replacing any earlier recording.

        The JSON goes to a temporary file in the same folder that is then renamed over the
        cassette, so a reader never sees half a file. When scrubbing removed anything, the
        result is checked to still be a valid cassette before it is written.

        Args:
            cassette: The cassette to save under its request hash.

        Returns:
            The path of the written file.

        Raises:
            CassetteSafetyError: If the scrubbed cassette is no longer valid; nothing is written.
        """
        data = cassette.model_dump(mode="json", by_alias=True)
        text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        text, removed = scrub(text)
        if removed:
            log.warning("scrubbed %s from cassette %s", ", ".join(removed), cassette.request_sha256)
            try:
                Cassette.model_validate_json(text)
            except ValidationError as exc:
                raise CassetteSafetyError(
                    f"cassette {cassette.request_sha256} is not valid after scrubbing; not saved"
                ) from exc
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(cassette.request_sha256)
        fd, tmp_name = tempfile.mkstemp(dir=self.root, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.chmod(tmp_name, 0o644)  # mkstemp makes 0600; cassettes are shared and committed
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return path
