"""
Run one ``claude -p`` call on the Claude subscription and read its JSON result (plan §8.2).

Every call:

- passes the full flag set from ``build_flags``, and never ``--bare`` (it only accepts an
  API key);
- sends the prompt on stdin, so it never shows in the process list or hits argv limits;
- runs in a fresh, empty temporary directory;
- gets the parent environment minus the variables ``child_env`` strips, ``ANTHROPIC_API_KEY``
  first among them.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lansh.config import env
from lansh.llm.errors import (
    ClaudeCallError,
    ClaudeNotFoundError,
    ClaudeTimeoutError,
    StructuredOutputError,
    UsageLimitError,
)
from lansh.llm.request import ClaudeRequest, canonical_json

log = logging.getLogger(__name__)

# set LANSH_CLAUDE_BIN to the claude executable when it isn't on PATH
BINARY_ENV = "LANSH_CLAUDE_BIN"

# seconds before a call is killed; Opus at high effort on a whole job can take minutes
DEFAULT_TIMEOUT_S = 600.0

# variables with these prefixes never reach claude: ANTHROPIC_* holds API credentials and
# endpoints (ANTHROPIC_API_KEY would bill an API account instead of the subscription), and
# CLAUDE_CODE_* is Claude Code configuration, including CLAUDE_CODE_EFFORT_LEVEL, which
# overrides --effort, and the variables a parent Claude Code session exports to its children;
# like --setting-sources "" for settings files, this keeps every call independent of the
# machine it runs on
STRIPPED_PREFIXES: tuple[str, ...] = ("ANTHROPIC_", "CLAUDE_CODE_")

# further variables that never reach claude: the rest of what a parent Claude Code session
# exports, knobs that change how a call behaves, and LANSH's own secrets
STRIPPED_NAMES: frozenset[str] = frozenset(
    {
        "CLAUDECODE",
        "CLAUDE_PID",
        "CLAUDE_EFFORT",
        "CLAUDE_AGENT_SDK_VERSION",
        "AI_AGENT",
        "MCP_CONNECTION_NONBLOCKING",
        "MAX_THINKING_TOKENS",
        "MAX_STRUCTURED_OUTPUT_RETRIES",
        "MSSQL_SA_PASSWORD",
    }
)

# kept although it matches a stripped prefix: how a headless machine signs in to the
# subscription (claude setup-token)
KEPT_NAMES: frozenset[str] = frozenset({"CLAUDE_CODE_OAUTH_TOKEN"})

# how the CLI words a usage or rate limit (Claude Code 2.1.x and earlier formats); "limit
# reached" alone also ends "Context limit reached", which is a full context window, not quota
_USAGE_LIMIT = re.compile(
    r"usage limit|(?<!context )limit reached|(?:hit|reached) your\b[^.\n]{0,40}?\blimit|"
    r"out of usage|spend limit|shared budget|rate[ _-]?limit",
    re.IGNORECASE,
)
_RESETS = re.compile(r"\bresets?\s+(?:at\s+)?([^\n|·.]+)", re.IGNORECASE)
_EPOCH_SUFFIX = re.compile(r"\|(\d{9,11})\s*$")


def child_env(parent: Mapping[str, str] | None = None) -> dict[str, str]:
    """
    Build the environment for a ``claude`` call: ``parent`` minus the stripped variables.

    A variable is stripped when it is in ``STRIPPED_NAMES`` or starts with one of
    ``STRIPPED_PREFIXES``, unless it is in ``KEPT_NAMES``.

    Args:
        parent: The environment to start from; ``os.environ`` when not given.

    Returns:
        A new dict; ``parent`` itself is left unchanged.
    """
    source = os.environ if parent is None else parent
    return {
        name: value
        for name, value in source.items()
        if name in KEPT_NAMES or not (name in STRIPPED_NAMES or name.startswith(STRIPPED_PREFIXES))
    }


def resolve_binary() -> str:
    """
    Find the ``claude`` executable.

    Returns:
        ``LANSH_CLAUDE_BIN`` if it is set, otherwise ``claude`` from ``PATH``.

    Raises:
        ClaudeNotFoundError: If ``LANSH_CLAUDE_BIN`` is unset and ``claude`` isn't on ``PATH``.
    """
    found = env(BINARY_ENV) or shutil.which("claude")
    if not found:
        raise ClaudeNotFoundError(
            "claude command not found: install Claude Code (README.md setup step 3) "
            f"or set {BINARY_ENV}"
        )
    return found


def build_flags(request: ClaudeRequest[Any]) -> list[str]:
    """
    List every argument of one call after the binary (plan §8.2).

    The prompt isn't among them: it goes on stdin. The last four flags give the call no
    built-in tools, no user settings or plugins and no MCP servers, and stop its session
    being saved.

    Args:
        request: The request whose schema, system prompt, model and effort are passed.

    Returns:
        The arguments, always in the same order.
    """
    return [
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        canonical_json(request.json_schema),
        "--system-prompt",
        request.system_prompt,
        "--model",
        request.model,
        "--effort",
        request.effort,
        "--tools",
        "",
        "--setting-sources",
        "",
        "--no-session-persistence",
        "--strict-mcp-config",
    ]


def is_usage_limit(text: str) -> bool:
    """
    Tell whether an error message from the CLI means a usage or rate limit.

    Args:
        text: The message, from stderr or from the result envelope.

    Returns:
        True when it matches one of the CLI's known wordings.
    """
    return bool(_USAGE_LIMIT.search(text))


def _resets_hint(text: str) -> str | None:
    """
    Pick out when a usage limit resets from the CLI's limit message.

    Returns:
        ``epoch <seconds>`` from an older CLI, the words after "resets" from a newer one, or
        None when the message gives no time.
    """
    epoch = _EPOCH_SUFFIX.search(text)  # older CLIs: "Claude AI usage limit reached|1752775200"
    if epoch:
        return f"epoch {epoch.group(1)}"
    match = _RESETS.search(text)
    return match.group(1).strip() if match else None


def _tail(text: str | None, limit: int = 500) -> str:
    """
    Strip text and keep at most its last ``limit`` characters, marking a cut with "…".
    """
    text = (text or "").strip()
    return text if len(text) <= limit else "…" + text[-limit:]


def _int(value: Any, default: int = 0) -> int:
    """
    Read a JSON count as an int, or give ``default`` when it is missing or not a number.

    A boolean doesn't count as a number here, although Python treats it as an int. Every
    value read this way is a count or a duration, so a negative one is clamped to 0 rather
    than allowed to fail the usage record and hide the call's real outcome.
    """
    if isinstance(value, int | float) and not isinstance(value, bool):
        return max(0, int(value))
    return default


def _opt_int(value: Any) -> int | None:
    """
    Read a JSON number as an int, or give None when it is missing or not a number.
    """
    return _int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class CallMetrics:
    """
    What one result envelope reports about the call, whether it succeeded or not.

    Attributes:
        subtype: The envelope's ``subtype``, such as ``success``.
        is_error: Whether the CLI marked the call as failed.
        duration_ms: How long the call took as the CLI measured it, start-up excluded.
        duration_api_ms: How much of that was spent on API requests, when reported.
        num_turns: Turns the call took, when reported.
        total_cost_usd: What the call would cost on the API, in US dollars; nothing is billed.
        usage: The envelope's ``usage``, summed over all turns of the call.
        model_usage: The envelope's ``modelUsage``: tokens and cost for each model that
            answered.
        stop_reason: Why the model stopped, when reported.
        errors: The envelope's error messages, if any.
        envelope_keys: The envelope's top-level keys, sorted.
        cli_version: The Claude Code version that answered.
        result_text: The envelope's ``result`` text: Claude's own words when it gave no
            structured answer.
    """

    subtype: str | None
    is_error: bool
    duration_ms: int
    duration_api_ms: int | None
    num_turns: int | None
    total_cost_usd: float
    usage: dict[str, Any]
    model_usage: dict[str, Any]
    stop_reason: str | None
    errors: tuple[str, ...]
    envelope_keys: tuple[str, ...]
    cli_version: str | None
    result_text: str = ""

    @classmethod
    def from_envelope(cls, envelope: Mapping[str, Any], cli_version: str | None) -> CallMetrics:
        """
        Read the metrics from a result envelope, tolerating missing or mistyped fields.

        Args:
            envelope: The parsed JSON that ``claude -p --output-format json`` printed.
            cli_version: The CLI version, from ``claude --version``.

        Returns:
            The metrics. A missing count reads as 0 or None, a missing text as None or "".
        """
        cost = envelope.get("total_cost_usd")
        subtype = envelope.get("subtype")
        stop_reason = envelope.get("stop_reason")
        result = envelope.get("result")
        return cls(
            subtype=subtype if isinstance(subtype, str) else None,
            is_error=bool(envelope.get("is_error")),
            duration_ms=_int(envelope.get("duration_ms")),
            duration_api_ms=_opt_int(envelope.get("duration_api_ms")),
            num_turns=_opt_int(envelope.get("num_turns")),
            total_cost_usd=float(cost) if isinstance(cost, int | float) else 0.0,
            usage=dict(envelope.get("usage") or {}),
            model_usage=dict(envelope.get("modelUsage") or {}),
            stop_reason=stop_reason if isinstance(stop_reason, str) else None,
            errors=tuple(str(e) for e in envelope.get("errors") or ()),
            envelope_keys=tuple(sorted(envelope)),
            cli_version=cli_version,
            result_text=result if isinstance(result, str) else "",
        )

    @property
    def models_used(self) -> list[str]:
        """
        The models that actually answered, from ``modelUsage``, sorted.
        """
        return sorted(self.model_usage)

    def token_totals(self) -> dict[str, int]:
        """
        Sum the tokens over every model in ``modelUsage``, or read ``usage`` when that is empty.

        Returns:
            Counts keyed ``input``, ``output``, ``cache_read`` and ``cache_creation``.
        """
        if self.model_usage:
            per_model = [m for m in self.model_usage.values() if isinstance(m, Mapping)]
            return {
                "input": sum(_int(m.get("inputTokens")) for m in per_model),
                "output": sum(_int(m.get("outputTokens")) for m in per_model),
                "cache_read": sum(_int(m.get("cacheReadInputTokens")) for m in per_model),
                "cache_creation": sum(_int(m.get("cacheCreationInputTokens")) for m in per_model),
            }
        return {
            "input": _int(self.usage.get("input_tokens")),
            "output": _int(self.usage.get("output_tokens")),
            "cache_read": _int(self.usage.get("cache_read_input_tokens")),
            "cache_creation": _int(self.usage.get("cache_creation_input_tokens")),
        }


@dataclass(frozen=True)
class ClaudeReply:
    """
    A successful call: the answer as Claude Code validated it, plus the call's metrics.
    """

    structured_output: dict[str, Any]
    metrics: CallMetrics


def _json_object(stdout: str) -> dict[str, Any] | None:
    """
    Find the result envelope on stdout: the whole of it, or else its last line.

    Returns:
        The envelope, or None when neither is a JSON object.
    """
    text = stdout.strip()
    if not text:
        return None
    for candidate in (text, text.splitlines()[-1]):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _error_message(envelope: Mapping[str, Any]) -> str:
    """
    Choose the message of a failed envelope: its errors, else its result, else its subtype.
    """
    errors = envelope.get("errors")
    if isinstance(errors, list) and errors:
        return _tail("; ".join(str(e) for e in errors))
    result = envelope.get("result")
    if isinstance(result, str) and result.strip():
        return _tail(result)
    return str(envelope.get("subtype") or "no message")


def parse_result(
    stdout: str, stderr: str, returncode: int, *, cli_version: str | None = None
) -> ClaudeReply:
    """
    Turn the output of ``claude -p --output-format json`` into a reply or an exception.

    Args:
        stdout: What the CLI printed, normally one JSON result envelope.
        stderr: What the CLI printed on stderr; quoted when something goes wrong.
        returncode: The CLI's exit code.
        cli_version: The CLI version, kept in the metrics.

    Returns:
        The answer as Claude Code validated it, with the call's metrics.

    Raises:
        UsageLimitError: If the CLI reports a usage or rate limit.
        StructuredOutputError: If there is no structured answer, because Claude Code gave up
            on the schema or because Claude answered in prose.
        ClaudeCallError: For any other failure, a non-zero exit code included.
    """
    envelope = _json_object(stdout)
    if envelope is None:
        detail = _tail(stderr) or _tail(stdout) or "no output"
        if is_usage_limit(detail):
            raise UsageLimitError(detail, resets=_resets_hint(detail))
        raise ClaudeCallError(f"claude exited with code {returncode} and no JSON result: {detail}")
    if envelope.get("type") != "result":
        raise ClaudeCallError(f"claude printed JSON that isn't a result: {_tail(stdout, 200)}")

    metrics = CallMetrics.from_envelope(envelope, cli_version)
    if metrics.is_error:
        message = _error_message(envelope)
        if is_usage_limit(message):
            raise UsageLimitError(
                message, resets=_resets_hint(message), subtype=metrics.subtype, metrics=metrics
            )
        if metrics.subtype == "error_max_structured_output_retries":
            raise StructuredOutputError(
                f"Claude could not satisfy the JSON schema: {message}",
                subtype=metrics.subtype,
                metrics=metrics,
            )
        raise ClaudeCallError(
            f"claude reported an error ({metrics.subtype}): {message}",
            subtype=metrics.subtype,
            metrics=metrics,
        )
    if returncode != 0:
        raise ClaudeCallError(
            f"claude exited with code {returncode}: {_tail(stderr) or 'no message'}",
            subtype=metrics.subtype,
            metrics=metrics,
        )
    structured = envelope.get("structured_output")
    if not isinstance(structured, dict) and is_usage_limit(metrics.result_text):
        # a limit can also arrive as the text of a result the CLI didn't mark as an error
        raise UsageLimitError(
            _tail(metrics.result_text),
            resets=_resets_hint(metrics.result_text),
            subtype=metrics.subtype,
            metrics=metrics,
        )
    if not isinstance(structured, dict):
        # seen live (spike 0.4): when no answer can satisfy the schema, Claude may stop calling
        # the structured-output tool and end its turn in prose; the CLI then reports subtype
        # "success" and is_error false, with no structured_output key at all
        got = "" if structured is None else f" (got {type(structured).__name__})"
        said = f"; Claude said: {_tail(metrics.result_text, 300)}" if metrics.result_text else ""
        raise StructuredOutputError(
            f"the result has no structured_output object{got}{said}",
            subtype=metrics.subtype,
            metrics=metrics,
        )
    return ClaudeReply(structured_output=structured, metrics=metrics)


class ClaudeCodeBackend:
    """
    Runs ``claude -p`` as a subprocess, on the subscription Claude Code is signed in to.

    The binary is resolved on first use, so a gateway in replay mode never needs Claude Code.
    """

    def __init__(self, binary: str | None = None, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        """
        Set up a backend without looking for the binary yet.

        Args:
            binary: Path of the ``claude`` executable; ``resolve_binary`` finds it on first
                use when not given.
            timeout_s: Seconds a call may run before it is killed.
        """
        self._binary = binary
        self.timeout_s = timeout_s
        self._version: str | None = None

    @property
    def binary(self) -> str:
        """
        The ``claude`` executable, resolved on first use.

        Raises:
            ClaudeNotFoundError: If it can't be found.
        """
        if self._binary is None:
            self._binary = resolve_binary()
        return self._binary

    def argv(self, request: ClaudeRequest[Any]) -> list[str]:
        """
        Build the exact command line of one call.

        Args:
            request: The request to build it for.

        Returns:
            The binary followed by ``build_flags(request)``; the prompt isn't part of it.
        """
        return [self.binary, *build_flags(request)]

    def _run(
        self, argv: list[str], *, stdin: str, timeout_s: float
    ) -> subprocess.CompletedProcess[str]:
        """
        Run a command in a fresh, empty temporary directory with the stripped environment.

        Output is read as UTF-8, with any undecodable bytes replaced.

        Raises:
            ClaudeTimeoutError: If the command runs longer than ``timeout_s``; it is killed.
            ClaudeNotFoundError: If the command can't be started.
        """
        with tempfile.TemporaryDirectory(prefix="lansh-claude-") as empty_dir:
            try:
                return subprocess.run(
                    argv,
                    input=stdin,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=empty_dir,
                    env=child_env(),
                    timeout=timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise ClaudeTimeoutError(
                    f"claude did not finish within {timeout_s:.0f} s and was stopped"
                ) from None
            except OSError as exc:
                raise ClaudeNotFoundError(f"could not start claude: {exc.strerror}") from exc

    def version(self) -> str:
        """
        Ask ``claude --version`` for the CLI version, once per backend.

        Returns:
            The version number, such as ``2.1.311``.

        Raises:
            ClaudeCallError: If the command fails or prints nothing.
        """
        if self._version is None:
            proc = self._run([self.binary, "--version"], stdin="", timeout_s=60.0)
            text = proc.stdout.strip()
            if proc.returncode != 0 or not text:
                raise ClaudeCallError(f"claude --version failed: {_tail(proc.stderr) or text}")
            self._version = text.split()[0]
        return self._version

    def run(self, request: ClaudeRequest[Any]) -> ClaudeReply:
        """
        Make one live call and parse its result.

        Args:
            request: The request to send; its prompt goes on stdin.

        Returns:
            The answer as Claude Code validated it, with the call's metrics.

        Raises:
            ClaudeCallError: If the call fails; the subclass, such as ``UsageLimitError`` or
                ``ClaudeTimeoutError``, says how.
            ClaudeNotFoundError: If ``claude`` can't be found or started.
        """
        cli_version = self.version()
        argv = self.argv(request)
        log.debug(
            "claude -p: agent=%s model=%s effort=%s request=%s",
            request.agent,
            request.model,
            request.effort,
            request.request_sha256[:12],
        )
        proc = self._run(argv, stdin=request.prompt, timeout_s=self.timeout_s)
        return parse_result(proc.stdout, proc.stderr, proc.returncode, cli_version=cli_version)
