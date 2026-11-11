"""
The Claude gateway: every Claude call in LANSH goes through ``ClaudeGateway.call``.

Modes (``LANSH_LLM_MODE``):

- ``live``: always call Claude, then record (or re-record) the answer;
- ``replay``: answer only from recorded cassettes; a missing one is an error;
- ``auto``: replay when a cassette exists and still validates, otherwise call live and record.

The default is ``replay``. Nothing can spend subscription quota unless someone opts in, the
offline tests and ``make demo`` need no Claude access, and a missing answer fails loudly
instead of quietly becoming a live call. Recording answers as they arrive is what lets a run
stopped by a usage limit resume in ``auto`` mode where it left off.

Claude Code checks the answer against the JSON schema; Pydantic then re-checks it against the
response model. On a Pydantic failure the gateway retries once, telling Claude what was
wrong, and then raises ``ValidationFailedError`` so the call can be escalated (plan §8.2).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from lansh.config import env
from lansh.contracts import LLMUsage
from lansh.llm.backend import CallMetrics, ClaudeCodeBackend, ClaudeReply, build_flags
from lansh.llm.cassette import (
    Cassette,
    CassetteStore,
    RecordedRequest,
    RecordedResponse,
    recorded_flags,
)
from lansh.llm.errors import (
    CassetteInvalidError,
    CassetteMissingError,
    ClaudeCallError,
    LiveCallCapError,
    StructuredOutputError,
    UsageLimitError,
    ValidationFailedError,
)
from lansh.llm.request import ClaudeRequest

log = logging.getLogger(__name__)

MODE_ENV = "LANSH_LLM_MODE"


class LLMMode(StrEnum):
    """
    How the gateway answers a request; the module docstring describes each mode.
    """

    LIVE = "live"
    REPLAY = "replay"
    AUTO = "auto"


# used when LANSH_LLM_MODE is unset or empty (the module docstring says why)
DEFAULT_MODE = LLMMode.REPLAY

# at most this many validation problems are quoted back to Claude on the retry
_MAX_RETRY_PROBLEMS = 20


def mode_from_env() -> LLMMode:
    """
    Read the mode from ``LANSH_LLM_MODE``, in the environment or ``.env``.

    Case and surrounding spaces don't matter.

    Returns:
        The mode, or ``DEFAULT_MODE`` when the variable is unset or empty.

    Raises:
        ValueError: If the variable names no known mode.
    """
    raw = env(MODE_ENV)
    if raw is None:
        return DEFAULT_MODE
    try:
        return LLMMode(raw.strip().lower())
    except ValueError:
        valid = ", ".join(m.value for m in LLMMode)
        raise ValueError(f"{MODE_ENV}={raw!r} is not one of: {valid}") from None


@dataclass(frozen=True)
class ClaudeResult[T: BaseModel]:
    """
    A validated answer and how it was obtained.

    Attributes:
        output: The answer, validated against the request's response model.
        request_sha256: The hash of the request as asked; a retry doesn't change it.
        replayed: True when the answer came from a cassette.
        attempts: Live calls it took to get a valid answer (1 or 2); for a replay, the
            number the cassette records.
        usage: One record per live ``claude -p`` call, or a single replayed record.
        cassette_path: Where the answer is recorded.
    """

    output: T
    request_sha256: str
    replayed: bool
    attempts: int
    usage: tuple[LLMUsage, ...]
    cassette_path: Path

    @property
    def live_calls(self) -> int:
        """
        How many live ``claude -p`` calls this result took; 0 for a replay.
        """
        return sum(not u.replayed for u in self.usage)


def _usage(
    request: ClaudeRequest[Any],
    sha: str,
    metrics: CallMetrics,
    *,
    replayed: bool,
    cli_version: str | None,
    attempt: int,
    outcome: str = "ok",
) -> LLMUsage:
    """
    Build the usage-log record of one call, live or replayed, under a fresh call id.

    The cost is clamped at 0, since ``LLMUsage`` refuses a negative one.

    Args:
        request: The request as sent.
        sha: The original request's hash, which every record of the request shares.
        metrics: What the CLI reported about the call, or what the cassette recorded.
        replayed: Whether the answer came from a cassette.
        cli_version: The Claude Code version that answered.
        attempt: 1 for the first try, 2 for the retry; for a replay, the recorded attempt.
        outcome: How the call went, one of ``LLMUsage.outcome``'s values.
    """
    tokens = metrics.token_totals()
    return LLMUsage(
        call_id=uuid.uuid4().hex,
        agent=request.agent,
        job_id=request.job_id,
        model_requested=request.model,
        models_used=metrics.models_used,
        effort=request.effort,
        cli_version=cli_version,
        request_sha256=sha,
        outcome=outcome,
        attempt=attempt,
        num_turns=metrics.num_turns,
        input_tokens=tokens["input"],
        output_tokens=tokens["output"],
        cache_read_tokens=tokens["cache_read"],
        cache_creation_tokens=tokens["cache_creation"],
        duration_ms=metrics.duration_ms,
        cost_usd_equivalent=max(metrics.total_cost_usd, 0.0),
        replayed=replayed,
    )


def _outcome(error: ClaudeCallError) -> str:
    """
    Classify a failed live call for its usage record.

    Returns:
        ``usage_limit`` for a usage or rate limit; ``refusal`` when the CLI reports the API's
        ``refusal`` stop reason; ``schema_invalid`` when there was no usable structured
        answer; ``error`` for anything else, such as a non-zero exit code.
    """
    if isinstance(error, UsageLimitError):
        return "usage_limit"
    if error.metrics is not None and error.metrics.stop_reason == "refusal":
        return "refusal"
    if isinstance(error, StructuredOutputError):
        return "schema_invalid"
    return "error"


def _metrics_from_cassette(cassette: Cassette) -> CallMetrics:
    """
    Rebuild the metrics of the call that recorded a cassette, for a replay's usage record.
    """
    response = cassette.response
    return CallMetrics(
        subtype="success",
        is_error=False,
        duration_ms=response.duration_ms,
        duration_api_ms=response.duration_api_ms,
        num_turns=response.num_turns,
        total_cost_usd=response.total_cost_usd,
        usage=response.usage,
        model_usage=response.model_usage,
        stop_reason=None,
        errors=(),
        envelope_keys=tuple(response.envelope_keys),
        cli_version=cassette.cli_version,
    )


def _retry_prompt(prompt: str, error: ValidationError) -> str:
    """
    Append the validation problems to the original prompt, for the one retry.

    Each problem names the field at fault; at most ``_MAX_RETRY_PROBLEMS`` are listed.
    """
    problems = [
        f"- {'.'.join(str(p) for p in e['loc']) or '(whole answer)'}: {e['msg']}"
        for e in error.errors(include_url=False, include_input=False)[:_MAX_RETRY_PROBLEMS]
    ]
    return (
        f"{prompt}\n\nYour previous answer was rejected by validation:\n"
        + "\n".join(problems)
        + "\nAnswer again, fixing these problems."
    )


# plan decision D5: at most this many live Claude calls per full run
D5_MAX_LIVE_CALLS = 150


def default_cap() -> int:
    """
    Read the live-call cap from ``LANSH_LLM_MAX_LIVE_CALLS``, else use D5's 150.

    Returns:
        The most live calls a gateway may make.

    Raises:
        ValueError: If the variable isn't a whole number.
    """
    return int(env("LANSH_LLM_MAX_LIVE_CALLS", str(D5_MAX_LIVE_CALLS)) or D5_MAX_LIVE_CALLS)


class ClaudeGateway:
    """
    Answers ``ClaudeRequest`` objects from cassettes or from live ``claude -p`` calls.

    ``max_live_calls`` caps live calls made through this gateway (plan decision D5: 150 per
    run by default, or ``LANSH_LLM_MAX_LIVE_CALLS``); the cap raises ``LiveCallCapError``
    before a call that would exceed it. There is no uncapped mode: None, given to the
    constructor or set later, means ``default_cap()``. ``live_calls`` counts the live calls
    made so far, failed ones included. ``usage_log`` keeps every ``LLMUsage`` record, failed
    live calls included when the CLI reported on them; each record's ``outcome`` says how the
    call went, and its ``attempt`` whether it was the first try or the retry.
    """

    def __init__(
        self,
        *,
        mode: LLMMode | str | None = None,
        backend: ClaudeCodeBackend | None = None,
        store: CassetteStore | None = None,
        max_live_calls: int | None = None,
    ) -> None:
        """
        Set up a gateway; Claude Code isn't needed until the first live call.

        Args:
            mode: How to answer; read from ``LANSH_LLM_MODE`` when not given.
            backend: What makes the live calls; a ``ClaudeCodeBackend`` when not given.
            store: Where answers are recorded; ``runs/cassettes/`` when not given.
            max_live_calls: The cap on live calls; ``default_cap()`` when not given or None.

        Raises:
            ValueError: If the mode (given or from ``LANSH_LLM_MODE``) is unknown, or
                ``LANSH_LLM_MAX_LIVE_CALLS`` isn't a whole number.
        """
        self.mode = LLMMode(mode) if mode is not None else mode_from_env()
        self.backend = backend if backend is not None else ClaudeCodeBackend()
        self.store = store if store is not None else CassetteStore()
        self.max_live_calls: int | None = (
            max_live_calls if max_live_calls is not None else default_cap()
        )
        self.live_calls = 0
        self.usage_log: list[LLMUsage] = []

    def call[T: BaseModel](self, request: ClaudeRequest[T]) -> ClaudeResult[T]:
        """
        Answer one request according to the gateway's mode.

        Args:
            request: What to ask Claude, and the model its answer must fit.

        Returns:
            The validated answer and how it was obtained.

        Raises:
            CassetteMissingError: In replay mode, if no answer is recorded.
            CassetteInvalidError: If the recorded answer is corrupt, or in replay mode no
                longer validates.
            LiveCallCapError: If a live call is needed but the cap is reached.
            ValidationFailedError: If Pydantic rejects the answer and the retry's answer too.
            ClaudeCallError: If a live call fails; a ``UsageLimitError`` means stop now and
                resume later in ``auto`` mode.
            ClaudeNotFoundError: If a live call is needed and ``claude`` can't be found or
                started.
        """
        sha = request.request_sha256
        if self.mode is not LLMMode.LIVE:
            replayed = self._replay(request, sha)
            if replayed is not None:
                return replayed
            if self.mode is LLMMode.REPLAY:
                raise CassetteMissingError(
                    f"no recorded answer for agent {request.agent}"
                    + (f", job {request.job_id}" if request.job_id else "")
                    + f" (request {sha}) in {self.store.root}; "
                    f"set {MODE_ENV}=auto to record it"
                )
        return self._live(request, sha)

    def _replay[T: BaseModel](self, request: ClaudeRequest[T], sha: str) -> ClaudeResult[T] | None:
        """
        Answer from the cassette store, if a usable answer is recorded there.

        Returns:
            The replayed result, or None when nothing is recorded or, in ``auto`` mode, when
            the recorded answer no longer validates and should be recorded afresh.

        Raises:
            CassetteInvalidError: If the cassette is corrupt, or in replay mode no longer
                validates.
        """
        cassette = self.store.load(sha)
        if cassette is None:
            return None
        try:
            output = request.response_model.model_validate(cassette.response.structured_output)
        except ValidationError as exc:
            if self.mode is LLMMode.REPLAY:
                raise CassetteInvalidError(
                    f"recorded answer {sha} no longer validates against "
                    f"{request.response_model.__name__}: {exc.error_count()} problems"
                ) from exc
            log.warning("recorded answer %s no longer validates; calling Claude again", sha[:12])
            return None
        usage = _usage(
            request,
            sha,
            _metrics_from_cassette(cassette),
            replayed=True,
            cli_version=cassette.cli_version,
            attempt=cassette.attempts,
        )
        self.usage_log.append(usage)
        log.info("claude replay: agent=%s request=%s", request.agent, sha[:12])
        return ClaudeResult(
            output=output,
            request_sha256=sha,
            replayed=True,
            attempts=cassette.attempts,
            usage=(usage,),
            cassette_path=self.store.path_for(sha),
        )

    def _invoke(
        self, request: ClaudeRequest[Any], sha: str, usages: list[LLMUsage], *, attempt: int
    ) -> ClaudeReply:
        """
        Make one live call, counting it against the cap and logging its usage.

        A failed call still counts against the cap.

        Args:
            request: The request to send; on a retry, the one with the amended prompt.
            sha: The original request's hash, also on a retry, so that every usage record
                and the cassette share one key.
            usages: The usage records of this request so far. This call's record is appended,
                even when the call fails, provided the CLI reported on it.
            attempt: 1 for the first try, 2 for the retry.

        Returns:
            The CLI's reply.

        Raises:
            LiveCallCapError: If the cap is already reached; no call is made.
            ClaudeCallError: If the call fails.
        """
        cap = self.max_live_calls if self.max_live_calls is not None else default_cap()
        if self.live_calls >= cap:
            raise LiveCallCapError(
                f"live-call cap of {cap} reached; recorded answers are kept, "
                f"so rerun with {MODE_ENV}=auto to continue"
            )
        self.live_calls += 1
        log.info(
            "claude live call %d: agent=%s job=%s model=%s effort=%s request=%s",
            self.live_calls,
            request.agent,
            request.job_id,
            request.model,
            request.effort,
            sha[:12],
        )
        try:
            reply = self.backend.run(request)
        except ClaudeCallError as exc:
            if exc.metrics is not None:
                usage = _usage(
                    request,
                    sha,
                    exc.metrics,
                    replayed=False,
                    cli_version=exc.metrics.cli_version,
                    attempt=attempt,
                    outcome=_outcome(exc),
                )
                usages.append(usage)
                self.usage_log.append(usage)
            raise
        usage = _usage(
            request,
            sha,
            reply.metrics,
            replayed=False,
            cli_version=reply.metrics.cli_version,
            attempt=attempt,
        )
        usages.append(usage)
        self.usage_log.append(usage)
        log.info(
            "claude answered in %.1f s: %d input + %d cache-read tokens, %d output tokens, "
            "$%.4f API-equivalent (not billed)",
            reply.metrics.duration_ms / 1000,
            usage.input_tokens,
            usage.cache_read_tokens,
            usage.output_tokens,
            usage.cost_usd_equivalent,
        )
        return reply

    def _live[T: BaseModel](self, request: ClaudeRequest[T], sha: str) -> ClaudeResult[T]:
        """
        Call Claude, retry once if Pydantic rejects the answer, and record the valid answer.

        The retry sends the original prompt plus the validation problems, but the cassette
        records the original request under its own hash, so a later replay of it finds the
        answer.

        Raises:
            ValidationFailedError: If the retry's answer is rejected too; nothing is recorded.
        """
        usages: list[LLMUsage] = []
        attempt_request: ClaudeRequest[T] = request
        retry_reason: str | None = None
        for attempt in (1, 2):
            reply = self._invoke(attempt_request, sha, usages, attempt=attempt)
            try:
                output = request.response_model.model_validate(reply.structured_output)
            except ValidationError as exc:
                # the call itself worked, so _invoke logged it as ok; Pydantic says otherwise
                usages[-1].outcome = "schema_invalid"
                if attempt == 2:
                    raise ValidationFailedError(
                        f"{request.agent}: answer rejected by {request.response_model.__name__} "
                        f"twice (request {sha}); escalate"
                    ) from exc
                retry_reason = f"{exc.error_count()} validation problems: " + "; ".join(
                    e["msg"] for e in exc.errors(include_url=False, include_input=False)[:5]
                )
                log.warning(
                    "%s: answer failed validation (%s); retrying once", request.agent, retry_reason
                )
                attempt_request = request.model_copy(
                    update={"prompt": _retry_prompt(request.prompt, exc)}
                )
                continue
            path = self.store.save(
                self._cassette(request, sha, reply, attempts=attempt, retry_reason=retry_reason)
            )
            return ClaudeResult(
                output=output,
                request_sha256=sha,
                replayed=False,
                attempts=attempt,
                usage=tuple(usages),
                cassette_path=path,
            )
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _cassette(
        request: ClaudeRequest[Any],
        sha: str,
        reply: ClaudeReply,
        *,
        attempts: int,
        retry_reason: str | None,
    ) -> Cassette:
        """
        Build the cassette of a valid answer, stamped with the current UTC time.
        """
        metrics = reply.metrics
        return Cassette(
            request_sha256=sha,
            request=RecordedRequest(
                agent=request.agent,
                job_id=request.job_id,
                model=request.model,
                effort=request.effort,
                system_prompt=request.system_prompt,
                prompt=request.prompt,
                json_schema=request.json_schema,
                flags=recorded_flags(build_flags(request)),
            ),
            response=RecordedResponse(
                structured_output=reply.structured_output,
                usage=metrics.usage,
                model_usage=metrics.model_usage,
                total_cost_usd=metrics.total_cost_usd,
                duration_ms=metrics.duration_ms,
                duration_api_ms=metrics.duration_api_ms,
                num_turns=metrics.num_turns,
                envelope_keys=list(metrics.envelope_keys),
            ),
            attempts=attempts,
            retry_reason=retry_reason,
            cli_version=metrics.cli_version or "unknown",
            recorded_at=datetime.now(UTC),
        )
