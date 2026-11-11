"""
Exceptions raised by the Claude gateway.

``UsageLimitError`` and ``LiveCallCapError`` mean "stop the run cleanly": every answer
recorded so far is in the cassette store, so a later run in ``auto`` mode resumes from there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# backend imports this module, so importing it back at run time would be circular
if TYPE_CHECKING:
    from lansh.llm.backend import CallMetrics


class ClaudeError(Exception):
    """
    Base class for every gateway error.
    """


class ClaudeNotFoundError(ClaudeError):
    """
    The ``claude`` command can't be found or started.
    """


class ClaudeCallError(ClaudeError):
    """
    A ``claude -p`` call failed.

    ``metrics`` holds what the CLI reported about the failed call (tokens, cost, turns), when
    it reported anything, so the usage log stays complete.
    """

    def __init__(
        self,
        message: str,
        *,
        subtype: str | None = None,
        metrics: CallMetrics | None = None,
    ) -> None:
        """
        Keep the envelope's subtype and the call's metrics with the message.

        Args:
            message: What went wrong, as shown to people.
            subtype: The result envelope's ``subtype``, when there was an envelope.
            metrics: What the CLI reported about the call, or None when it reported nothing.
        """
        super().__init__(message)
        self.subtype = subtype
        self.metrics = metrics


class UsageLimitError(ClaudeCallError):
    """
    The subscription's usage limit (or a rate limit) was reached.

    ``resets`` is the CLI's hint about when the limit resets, if it gave one.
    """

    def __init__(
        self,
        message: str,
        *,
        resets: str | None = None,
        subtype: str | None = None,
        metrics: CallMetrics | None = None,
    ) -> None:
        """
        Keep the CLI's reset hint along with what ``ClaudeCallError`` keeps.

        Args:
            message: The CLI's limit message.
            resets: When the limit resets, as the CLI worded it (or ``epoch <seconds>`` from
                older CLIs); None when the message gave no time.
            subtype: The result envelope's ``subtype``, when there was an envelope.
            metrics: What the CLI reported about the call, or None when it reported nothing.
        """
        super().__init__(message, subtype=subtype, metrics=metrics)
        self.resets = resets


class ClaudeTimeoutError(ClaudeCallError):
    """
    ``claude -p`` didn't finish within the backend's timeout and was killed.
    """


class StructuredOutputError(ClaudeCallError):
    """
    The call returned no usable ``structured_output``.

    Raised when Claude Code gave up on the schema (``error_max_structured_output_retries``)
    and when a successful result has no ``structured_output`` object.
    """


class ValidationFailedError(ClaudeError):
    """
    Pydantic rejected the answer and the one retry too: escalate to a human.
    """


class CassetteMissingError(ClaudeError):
    """
    Replay mode, and no answer is recorded for this request.
    """


class CassetteInvalidError(ClaudeError):
    """
    A recorded answer exists but can't be used (corrupt, or rejected by the response model).
    """


class CassetteSafetyError(ClaudeError):
    """
    A cassette can't be made safe to commit: scrubbing it left an invalid cassette.
    """


class LiveCallCapError(ClaudeError):
    """
    The run reached its cap on live Claude calls (plan decision D5).
    """
