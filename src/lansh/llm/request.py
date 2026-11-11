"""
What the gateway sends to Claude, and the hash that keys its recorded answer (plan §8.2).

The request hash is the SHA-256 of the normalised JSON (sorted keys, no insignificant
whitespace, UTF-8) of exactly five things: the model, the effort, the system prompt, the
prompt and the JSON schema. The agent and job are labels for the usage log; two agents that
send the same request share one recorded answer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lansh.contracts import CONTRACT_MODELS, JobId

# the levels Claude Code 2.1.311 accepts for --effort; it doesn't reject an unknown level but
# prints a warning and silently uses its default, so the gateway checks the level itself
Effort = Literal["low", "medium", "high", "xhigh", "max"]

# the model alias every agent uses by default (plan decision D4)
DEFAULT_MODEL = "opus"


def canonical_json(value: Any) -> str:
    """
    Serialise to normalised JSON: sorted keys, compact separators, non-ASCII text kept as UTF-8.

    Dict key order doesn't change the text, so the same request always hashes the same.

    Args:
        value: Anything ``json.dumps`` can serialise.

    Returns:
        The JSON text.

    Raises:
        ValueError: If ``value`` holds NaN or infinity, which JSON can't represent.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def sha256_hex(text: str) -> str:
    """
    Hash text with SHA-256.

    Args:
        text: The text to hash; it is encoded as UTF-8 first.

    Returns:
        The digest as 64 lower-case hex characters.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ClaudeRequest[T: BaseModel](BaseModel):
    """
    One structured Claude call: prompts, the response model and how hard to think.

    ``response_model`` defines the answer. Its JSON schema is sent with ``--json-schema``
    and Pydantic re-checks the answer against the model itself. Line endings in both prompts
    are normalised to ``\\n`` so that a checkout with CRLF endings hashes the same; nothing
    else in the text is changed (trailing spaces are data in this project).

    Attributes:
        agent: The agent making the call; a label for the usage log, not part of the hash.
        job_id: The job the call is about, if any; also only a label.
        system_prompt: Sent with ``--system-prompt``.
        prompt: Sent on stdin, never on the command line.
        response_model: The agent's own answer model; a contract record, or a subclass of
            one, is refused.
        model: The ``--model`` alias; ``opus`` unless the agent asks for another.
        effort: The ``--effort`` level, checked here because Claude Code silently ignores an
            unknown one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: str = Field(min_length=1, description="The agent making the call, for the usage log.")
    job_id: JobId | None = None
    system_prompt: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    response_model: type[T] = Field(exclude=True)
    model: str = Field(default=DEFAULT_MODEL, min_length=1)
    effort: Effort

    @field_validator("system_prompt", "prompt")
    @classmethod
    def _unix_newlines(cls, text: str) -> str:
        """
        Turn CRLF and lone CR line endings into LF, so the hash doesn't depend on the checkout.
        """
        return text.replace("\r\n", "\n").replace("\r", "\n")

    @field_validator("response_model")
    @classmethod
    def _not_a_record(cls, model: type[T]) -> type[T]:
        """
        Refuse a contract record as the response model, or a subclass of one.

        Records carry factory-owned fields (ids, hashes, ``verified``, decisions) that Claude
        must never fill in, and a subclass inherits them all. Agents answer in their own
        models instead (see the ``lansh.contracts`` docstring).

        Raises:
            ValueError: If ``model`` is in ``CONTRACT_MODELS`` or subclasses one; Pydantic
                reports it as a ``ValidationError``.
        """
        if issubclass(model, CONTRACT_MODELS):
            raise ValueError(f"{model.__name__} is a contract record, not an agent answer model")
        return model

    @property
    def json_schema(self) -> dict[str, Any]:
        """
        The JSON schema sent with ``--json-schema``: Pydantic's, ``$defs`` and ``$ref`` kept.

        It includes the response model's docstrings and field descriptions, so editing those
        changes the request hash, and answers recorded before the edit stop matching.
        """
        return self.response_model.model_json_schema(mode="validation")

    def hash_payload(self) -> dict[str, Any]:
        """
        Collect the five things the request hash covers.

        Returns:
            The model, the effort, both prompts and the JSON schema, keyed by name.
        """
        return {
            "model": self.model,
            "effort": self.effort,
            "system_prompt": self.system_prompt,
            "prompt": self.prompt,
            "json_schema": self.json_schema,
        }

    @property
    def request_sha256(self) -> str:
        """
        The key of this request's recorded answer.

        It is the SHA-256 of ``hash_payload()`` as canonical JSON, in lower-case hex.
        """
        return sha256_hex(canonical_json(self.hash_payload()))
