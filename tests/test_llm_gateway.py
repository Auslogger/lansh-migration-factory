"""
The Claude gateway calls ``claude -p`` as plan §8.2 sets out, replays answers and fails loudly.

Everything here runs offline: replays use recorded cassettes, and live paths run a fake
``claude`` (a small script printing canned result envelopes), as do the tests of ``make
smoke``'s Claude check and of the spike script. The one real call is marked ``live_llm`` and
is deselected by default. The CLI behaviour the fakes copy was observed in spike 0.4, unless
a test says otherwise.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import stat
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lansh.config import REPO_ROOT
from lansh.llm.backend import (
    ClaudeCodeBackend,
    build_flags,
    child_env,
    is_usage_limit,
)
from lansh.llm.cassette import Cassette, CassetteStore, RecordedRequest, recorded_flags
from lansh.llm.errors import (
    CassetteInvalidError,
    CassetteMissingError,
    ClaudeCallError,
    ClaudeTimeoutError,
    LiveCallCapError,
    StructuredOutputError,
    UsageLimitError,
    ValidationFailedError,
)
from lansh.llm.gateway import MODE_ENV, ClaudeGateway, LLMMode, mode_from_env
from lansh.llm.request import ClaudeRequest, canonical_json

SPIKE_SCRIPT = REPO_ROOT / "spikes" / "claude_backend.py"
SPIKE_CASSETTES = REPO_ROOT / "runs" / "cassettes" / "spike"
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "smoke_test.py"


### A response model, requests and canned envelopes

# leave these classes' docstrings as they are: the JSON schema includes them, so they feed
# the request hash that test_request_hash_is_stable pins


class Kind(StrEnum):
    SEMANTIC = "semantic"
    CONSTRUCT = "construct"


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Kind


class Answer(BaseModel):
    """Nested models and an enum (so the schema has $defs), plus a check JSON Schema can't do."""

    model_config = ConfigDict(extra="forbid")

    items: list[Item]
    total: int = Field(ge=0)

    @model_validator(mode="after")
    def _total_matches(self) -> Answer:
        if self.total != len(self.items):
            raise ValueError("total must equal the number of items")
        return self


VALID = {"items": [{"name": "status = 'OPEN'", "kind": "semantic"}], "total": 1}
# valid against the JSON schema, rejected by the model validator
WRONG_TOTAL = {"items": [{"name": "status = 'OPEN'", "kind": "semantic"}], "total": 2}


def make_request(**overrides: Any) -> ClaudeRequest[Answer]:
    """
    Build the T04 trap-scan request most tests send, with any field replaced from ``overrides``.
    """
    fields: dict[str, Any] = {
        "agent": "trap_scan",
        "job_id": "T04",
        "system_prompt": "You list traps.",
        "prompt": "WHERE status = 'OPEN'",
        "response_model": Answer,
        "effort": "high",
    }
    fields.update(overrides)
    return ClaudeRequest(**fields)


# the 27 keys of a successful Claude Code 2.1.311 result (spikes/README.md, "Claude backend")
ENVELOPE_KEYS_2_1_311 = (
    "api_error_status",
    "duration_api_ms",
    "duration_ms",
    "fast_mode_disabled_reason",
    "fast_mode_state",
    "first_content_frame_ms",
    "is_error",
    "modelUsage",
    "num_turns",
    "permission_denials",
    "queued_turn_count",
    "result",
    "result_index",
    "safety_stops",
    "session_id",
    "stop_reason",
    "structured_output",
    "subagent_stats",
    "subtype",
    "terminal_reason",
    "time_to_request_ms",
    "total_cost_usd",
    "ttft_ms",
    "ttft_stream_ms",
    "type",
    "usage",
    "uuid",
)


def envelope(structured_output: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    """
    Build a result envelope with the keys Claude Code 2.1.311 prints and made-up values.

    Args:
        structured_output: The answer. None leaves the key out, as when Claude answers in prose.
        overrides: Keys to replace or add, such as ``is_error``, ``subtype`` or ``errors``.
    """
    data: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "api_error_status": None,
        "duration_ms": 4321,
        "duration_api_ms": 4000,
        "time_to_request_ms": 120,
        "ttft_ms": 900,
        "ttft_stream_ms": 950,
        "first_content_frame_ms": 1000,
        "num_turns": 2,
        "result": "",
        "result_index": 0,
        "stop_reason": "end_turn",
        "terminal_reason": "completed",
        "session_id": "00000000-0000-4000-8000-000000000000",
        "total_cost_usd": 0.0421,
        "fast_mode_state": "off",
        "fast_mode_disabled_reason": None,
        "queued_turn_count": 0,
        "safety_stops": 0,
        "subagent_stats": {},
        "usage": {
            "input_tokens": 12,
            "output_tokens": 345,
            "cache_read_input_tokens": 6000,
            "cache_creation_input_tokens": 700,
        },
        "modelUsage": {
            "claude-opus-5-5": {
                "inputTokens": 12,
                "outputTokens": 345,
                "cacheReadInputTokens": 6000,
                "cacheCreationInputTokens": 700,
                "costUSD": 0.0421,
            }
        },
        "permission_denials": [],
        "uuid": "00000000-0000-4000-8000-000000000001",
    }
    if structured_output is not None:
        data["structured_output"] = structured_output
    data.update(overrides)
    return data


### A fake claude binary

# the fake ``claude`` program. It reports version 9.9.9, plays one scripted step per call
# and saves what each call was given
_FAKE_CLAUDE = """\
import json, os, sys, time
from pathlib import Path

here = Path(__file__).parent
if sys.argv[1:] == ["--version"]:
    print("9.9.9 (Claude Code)")
    sys.exit(0)
steps = json.loads((here / "steps.json").read_text())
counter = here / "count"
n = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n + 1))
step = steps[min(n, len(steps) - 1)]
seen = {
    "argv": sys.argv[1:],
    "env": sorted(os.environ),
    "cwd": os.getcwd(),
    "cwd_entries": sorted(os.listdir(".")),
    "stdin": sys.stdin.read(),
}
(here / f"call{n}.json").write_text(json.dumps(seen))
time.sleep(step.get("sleep", 0))
sys.stdout.write(step["stdout"] if "stdout" in step else json.dumps(step["envelope"]))
sys.stderr.write(step.get("stderr", ""))
sys.exit(step.get("exit", 0))
"""


@dataclass
class FakeClaude:
    """
    A stand-in ``claude`` that plays scripted steps and records what each call was given.
    """

    home: Path
    binary: Path

    def script(self, *steps: dict[str, Any]) -> None:
        """
        Set the steps the next calls play in order, and restart the call count.

        Args:
            steps: One dict per call: an ``envelope`` to print as JSON or raw ``stdout``, and
                optionally ``stderr``, ``exit`` and ``sleep`` (seconds). Calls past the last
                step repeat it.
        """
        (self.home / "steps.json").write_text(json.dumps(list(steps)))
        (self.home / "count").unlink(missing_ok=True)

    def calls(self) -> list[dict[str, Any]]:
        """
        Return what each call so far was given, in order.

        Returns:
            One dict per call with ``argv``, ``env`` (names only), ``cwd``, ``cwd_entries``
            and ``stdin``.
        """
        count = int((self.home / "count").read_text()) if (self.home / "count").exists() else 0
        return [json.loads((self.home / f"call{n}.json").read_text()) for n in range(count)]

    def backend(self, timeout_s: float = 30.0) -> ClaudeCodeBackend:
        """
        Build a backend that runs this fake instead of the real ``claude``.
        """
        return ClaudeCodeBackend(str(self.binary), timeout_s=timeout_s)


@pytest.fixture
def fake_claude(tmp_path: Path) -> FakeClaude:
    """
    Install a fake ``claude`` in a temporary folder.
    """
    home = tmp_path / "fake"
    home.mkdir()
    (home / "fake_claude.py").write_text(_FAKE_CLAUDE)
    binary = home / "claude"
    script = home / "fake_claude.py"
    binary.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))} "$@"\n'
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return FakeClaude(home=home, binary=binary)


def _no_subprocess(*args: object, **kwargs: object) -> None:
    """
    Stand in for ``subprocess.run`` and ``Popen``, and fail the test if called.
    """
    raise AssertionError("this test must not start a subprocess")


@pytest.fixture
def no_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Fail the test if it starts any subprocess.
    """
    monkeypatch.setattr(subprocess, "run", _no_subprocess)
    monkeypatch.setattr(subprocess, "Popen", _no_subprocess)


def _load_script(path: Path, name: str) -> ModuleType:
    """
    Import a script that isn't part of the package, under a module name of its own.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # register it first: Pydantic resolves the spike models' postponed annotations there
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_spike() -> ModuleType:
    """
    Import the spike script, to reuse the request it recorded and its answer model.
    """
    return _load_script(SPIKE_SCRIPT, "lansh_spike_claude_backend")


### Command line and environment


def test_argv_has_every_flag_and_never_bare() -> None:
    request = make_request()
    argv = ClaudeCodeBackend("/opt/claude").argv(request)

    assert argv == [
        "/opt/claude",
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        canonical_json(Answer.model_json_schema()),
        "--system-prompt",
        "You list traps.",
        "--model",
        "opus",
        "--effort",
        "high",
        "--tools",
        "",
        "--setting-sources",
        "",
        "--no-session-persistence",
        "--strict-mcp-config",
    ]
    assert "--bare" not in argv
    assert request.prompt not in argv  # the prompt goes on stdin
    assert "$defs" in json.loads(argv[argv.index("--json-schema") + 1])


def test_unknown_effort_is_rejected_before_any_call() -> None:
    # the CLI would only warn and fall back to its default effort
    with pytest.raises(ValidationError, match="effort"):
        make_request(effort="extreme")


def test_recorded_flags_hold_placeholders_for_the_system_prompt_and_schema() -> None:
    """
    A cassette's flags stand in for the system prompt and schema; the prompt is never there.
    """
    request = make_request()
    flags = recorded_flags(build_flags(request))
    assert {"<system_prompt>", "<json_schema>"} <= set(flags)
    assert request.system_prompt not in flags
    assert canonical_json(request.json_schema) not in flags
    assert request.prompt not in flags  # it goes on stdin
    description = RecordedRequest.model_fields["flags"].description or ""
    assert "system prompt" in description
    assert "JSON schema" in description


def test_child_env_strips_api_key_and_parent_session() -> None:
    """
    Only plain variables and the OAuth token for headless sign-in reach the child ``claude``.
    """
    parent = {
        "PATH": "/usr/bin",
        "HOME": "/home/someone",
        "LANG": "en_IE.UTF-8",
        "LANSH_LLM_MODE": "auto",
        "ANTHROPIC_API_KEY": "sk-ant-dummy",
        "ANTHROPIC_AUTH_TOKEN": "dummy",
        "ANTHROPIC_BASE_URL": "http://localhost:1",
        "CLAUDE_CODE_EFFORT_LEVEL": "max",
        "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
        "CLAUDE_CODE_SESSION_ID": "abc",
        "CLAUDE_CODE_MESSAGING_TOKEN": "dummy",
        "CLAUDECODE": "1",
        "CLAUDE_EFFORT": "high",
        "MSSQL_SA_PASSWORD": "dummy",
        "CLAUDE_CODE_OAUTH_TOKEN": "kept-for-headless-sign-in",
    }
    assert set(child_env(parent)) == {
        "PATH",
        "HOME",
        "LANG",
        "LANSH_LLM_MODE",
        "CLAUDE_CODE_OAUTH_TOKEN",
    }


def test_live_call_runs_in_empty_dir_without_api_key(
    fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    A live call gets the exact flags and an empty folder, and its usage record is complete.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "max")
    monkeypatch.setenv("CLAUDECODE", "1")
    fake_claude.script({"envelope": envelope(VALID)})
    request = make_request()
    gateway = ClaudeGateway(
        mode="live", backend=fake_claude.backend(), store=CassetteStore(tmp_path / "cassettes")
    )

    result = gateway.call(request)

    (seen,) = fake_claude.calls()
    assert seen["argv"] == build_flags(request)
    assert seen["stdin"] == request.prompt
    assert {"ANTHROPIC_API_KEY", "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDECODE"}.isdisjoint(seen["env"])
    assert "PATH" in seen["env"]
    assert seen["cwd_entries"] == []
    assert Path(seen["cwd"]).name.startswith("lansh-claude-")
    assert not Path(seen["cwd"]).exists()  # removed after the call

    assert result.output == Answer.model_validate(VALID)
    assert not result.replayed
    assert result.attempts == 1
    (usage,) = result.usage
    assert usage.agent == "trap_scan"
    assert usage.job_id == "T04"
    assert usage.model_requested == "opus"
    assert usage.models_used == ["claude-opus-5-5"]
    assert usage.effort == "high"
    assert usage.cli_version == "9.9.9"
    assert usage.request_sha256 == request.request_sha256
    assert (usage.input_tokens, usage.output_tokens) == (12, 345)
    assert (usage.cache_read_tokens, usage.cache_creation_tokens) == (6000, 700)
    assert usage.duration_ms == 4321
    assert usage.cost_usd_equivalent == pytest.approx(0.0421)
    assert (usage.outcome, usage.attempt, usage.num_turns) == ("ok", 1, 2)
    assert not usage.replayed
    assert gateway.usage_log == [usage]
    assert gateway.live_calls == 1


### Request hash


def test_request_hash_is_stable() -> None:
    request = make_request()
    assert request.request_sha256 == make_request().request_sha256
    # pinned: if this changes, every recorded answer stops matching, so change it only on purpose
    assert request.request_sha256 == PINNED_REQUEST_SHA256


def test_request_hash_ignores_labels_and_line_endings() -> None:
    base = make_request().request_sha256
    assert make_request(agent="other_agent", job_id=None).request_sha256 == base
    crlf = make_request(system_prompt="You list traps.", prompt="WHERE status = 'OPEN'\r\n")
    assert crlf.prompt == "WHERE status = 'OPEN'\n"
    assert crlf.request_sha256 == make_request(prompt="WHERE status = 'OPEN'\n").request_sha256


class OtherAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[str]


@pytest.mark.parametrize(
    "change",
    [
        {"model": "sonnet"},
        {"effort": "low"},
        {"system_prompt": "You list traps carefully."},
        {"prompt": "WHERE status = 'OPEN '"},  # a trailing space is data
        {"response_model": OtherAnswer},
    ],
)
def test_request_hash_covers_model_effort_prompts_and_schema(change: dict[str, Any]) -> None:
    assert make_request(**change).request_sha256 != make_request().request_sha256


### Replay


def test_replays_spike_cassette_without_starting_a_process(no_subprocess: None) -> None:
    spike = load_spike()
    request = spike.build_request()
    store = CassetteStore(SPIKE_CASSETTES)
    path = store.path_for(request.request_sha256)
    assert path.is_file(), "record it with: uv run python spikes/claude_backend.py --record"
    recorded = json.loads(path.read_text(encoding="utf-8"))

    gateway = ClaudeGateway(store=store)  # mode from the environment: replay
    result = gateway.call(request)

    assert gateway.mode is LLMMode.REPLAY
    assert result.replayed
    assert result.live_calls == 0
    assert result.output == spike.TrapScan.model_validate(recorded["response"]["structured_output"])
    assert {f.trap_id for f in result.output.findings} >= {"TSQL-01", "TSQL-04"}
    (usage,) = result.usage
    assert usage.replayed
    assert usage.models_used == sorted(recorded["response"]["modelUsage"])
    assert usage.cli_version == recorded["cli_version"]
    assert usage.cost_usd_equivalent == pytest.approx(recorded["response"]["total_cost_usd"])
    assert usage.output_tokens > 0
    assert usage.outcome == "ok"
    assert (usage.attempt, usage.num_turns) == (
        recorded["attempts"],
        recorded["response"]["num_turns"],
    )


def _secret_like_values() -> list[str]:
    """
    List secret-looking environment values, skipping short ones as the scrubber does.

    Each value comes as it is and JSON-escaped both ways, since a cassette is JSON.
    """
    names = ("PASSWORD", "PASSWD", "SECRET", "TOKEN", "API_KEY", "APIKEY", "CREDENTIAL")
    values = [
        value
        for name, value in os.environ.items()
        if any(n in name.upper() for n in names) and len(value) >= 8
    ]
    return [
        form
        for value in values
        for form in {value, json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1]}
    ]


def test_spike_cassettes_are_safe_to_commit() -> None:
    paths = sorted(SPIKE_CASSETTES.glob("*.json"))
    assert paths
    secrets = _secret_like_values()
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert str(Path.home()) not in text
        assert str(REPO_ROOT) not in text
        assert "/Users/" not in text
        assert "ANTHROPIC_API_KEY" not in text
        assert not any(secret in text for secret in secrets)
        cassette = Cassette.model_validate_json(text)
        assert path.stem == cassette.request_sha256
        assert "--bare" not in cassette.request.flags
        assert not any(flag.startswith("/") for flag in cassette.request.flags)


def test_replay_without_cassette_fails_loudly(no_subprocess: None, tmp_path: Path) -> None:
    gateway = ClaudeGateway(mode="replay", store=CassetteStore(tmp_path))
    with pytest.raises(CassetteMissingError, match="LANSH_LLM_MODE=auto"):
        gateway.call(make_request())


def test_default_mode_is_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MODE_ENV)
    assert mode_from_env() is LLMMode.REPLAY
    assert ClaudeGateway().mode is LLMMode.REPLAY


def test_unknown_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MODE_ENV, "turbo")
    with pytest.raises(ValueError, match="live, replay, auto"):
        mode_from_env()


def test_auto_records_once_then_replays(fake_claude: FakeClaude, tmp_path: Path) -> None:
    fake_claude.script({"envelope": envelope(VALID)})
    store = CassetteStore(tmp_path / "cassettes")
    request = make_request()

    first = ClaudeGateway(mode="auto", backend=fake_claude.backend(), store=store).call(request)
    second = ClaudeGateway(mode="auto", backend=fake_claude.backend(), store=store).call(request)

    assert len(fake_claude.calls()) == 1
    assert not first.replayed
    assert second.replayed
    assert second.output == first.output
    assert first.cassette_path == second.cassette_path == store.path_for(request.request_sha256)
    cassette = store.load(request.request_sha256)
    assert cassette is not None
    assert cassette.request.flags[0] == "-p"
    assert "<system_prompt>" in cassette.request.flags
    assert "<json_schema>" in cassette.request.flags
    assert cassette.cli_version == "9.9.9"
    assert cassette.response.envelope_keys == sorted(envelope(VALID))


def test_stale_cassette_is_rejected_in_replay_and_rerecorded_in_auto(
    fake_claude: FakeClaude, tmp_path: Path
) -> None:
    fake_claude.script({"envelope": envelope(VALID)})
    store = CassetteStore(tmp_path / "cassettes")
    request = make_request()
    live = ClaudeGateway(mode="live", backend=fake_claude.backend(), store=store).call(request)
    path = live.cassette_path
    data = json.loads(path.read_text())
    data["response"]["structured_output"] = WRONG_TOTAL  # as if the response model had tightened
    path.write_text(json.dumps(data))

    with pytest.raises(CassetteInvalidError):
        ClaudeGateway(mode="replay", store=store).call(request)
    again = ClaudeGateway(mode="auto", backend=fake_claude.backend(), store=store).call(request)
    assert not again.replayed
    assert json.loads(path.read_text())["response"]["structured_output"] == VALID


### Errors, usage limits and validation


@pytest.mark.parametrize(
    ("step", "error", "resets"),
    [
        (
            {
                "envelope": envelope(
                    None, is_error=True, result="You've hit your limit · resets 7pm (Europe/Dublin)"
                ),
                "exit": 1,
            },
            UsageLimitError,
            "7pm (Europe/Dublin)",
        ),
        (
            {"stdout": "Claude AI usage limit reached|1752775200", "exit": 1},
            UsageLimitError,
            "epoch 1752775200",
        ),
        (
            {"stdout": "", "stderr": "Error: 5-hour limit reached ∙ resets 3am", "exit": 1},
            UsageLimitError,
            "3am",
        ),
        (
            {
                "envelope": envelope(
                    None, is_error=True, subtype="error_during_execution", errors=["boom"]
                ),
                "exit": 1,
            },
            ClaudeCallError,
            None,
        ),
        (
            {
                "envelope": envelope(
                    None,
                    is_error=True,
                    subtype="error_max_structured_output_retries",
                    errors=["Failed to provide valid structured output after 5 attempts"],
                ),
                "exit": 1,
            },
            StructuredOutputError,
            None,
        ),
        ({"envelope": envelope(None)}, StructuredOutputError, None),
        ({"envelope": envelope(VALID), "exit": 1}, ClaudeCallError, None),
        ({"stdout": "not json", "stderr": "something broke", "exit": 2}, ClaudeCallError, None),
    ],
    ids=[
        "usage-limit",
        "usage-limit-old-format",
        "usage-limit-stderr",
        "is-error",
        "schema-unsatisfied",
        "no-structured-output",
        "non-zero-exit",
        "not-json",
    ],
)
def test_call_errors(
    fake_claude: FakeClaude,
    tmp_path: Path,
    step: dict[str, Any],
    error: type[Exception],
    resets: str | None,
) -> None:
    """
    Each failure raises its own error type, isn't retried and records no cassette.
    """
    fake_claude.script(step)
    store = CassetteStore(tmp_path / "cassettes")
    gateway = ClaudeGateway(mode="live", backend=fake_claude.backend(), store=store)

    with pytest.raises(error) as caught:
        gateway.call(make_request())

    assert type(caught.value) is error  # e.g. a usage limit isn't a plain call error
    if resets is not None:
        assert isinstance(caught.value, UsageLimitError)
        assert caught.value.resets == resets
    assert len(fake_claude.calls()) == 1  # errors are not retried
    assert not store.root.exists() or not any(store.root.iterdir())
    assert gateway.live_calls == 1
    # a failed call that reported metrics still lands in the usage log
    has_envelope = "envelope" in step
    assert len(gateway.usage_log) == (1 if has_envelope else 0)


@pytest.mark.parametrize(
    ("step", "outcome"),
    [
        (
            {"envelope": envelope(None, is_error=True, result="You've hit your limit"), "exit": 1},
            "usage_limit",
        ),
        (
            {
                "envelope": envelope(
                    None,
                    is_error=True,
                    subtype="error_max_structured_output_retries",
                    errors=["Failed to provide valid structured output after 5 attempts"],
                ),
                "exit": 1,
            },
            "schema_invalid",
        ),
        ({"envelope": envelope(None, num_turns=4, result="No number can pass.")}, "schema_invalid"),
        # not seen live: the API's refusal stop reason, which the CLI passes on as stop_reason
        ({"envelope": envelope(None, stop_reason="refusal")}, "refusal"),
        (
            {
                "envelope": envelope(
                    None, is_error=True, subtype="error_during_execution", errors=["boom"]
                ),
                "exit": 1,
            },
            "error",
        ),
        ({"envelope": envelope(VALID), "exit": 1}, "error"),
    ],
    ids=["usage-limit", "schema-unsatisfied", "prose", "refusal", "is-error", "non-zero-exit"],
)
def test_failed_call_is_logged_with_its_outcome(
    fake_claude: FakeClaude, tmp_path: Path, step: dict[str, Any], outcome: str
) -> None:
    """
    A failed call's usage record says how it failed, with its attempt and the turns it took.
    """
    fake_claude.script(step)
    gateway = ClaudeGateway(
        mode="live", backend=fake_claude.backend(), store=CassetteStore(tmp_path)
    )

    with pytest.raises(ClaudeCallError):
        gateway.call(make_request())

    (usage,) = gateway.usage_log
    assert (usage.outcome, usage.attempt) == (outcome, 1)
    assert usage.num_turns == step["envelope"]["num_turns"]


def test_test_envelope_matches_the_cli() -> None:
    assert sorted(envelope(VALID)) == sorted(ENVELOPE_KEYS_2_1_311)


def test_prose_instead_of_structured_output(fake_claude: FakeClaude, tmp_path: Path) -> None:
    # seen live twice (spikes/README.md, "Claude backend"): with a schema no answer can
    # satisfy, Claude gives up on the tool and explains in prose; the CLI still reports success
    said = "The form requires n to be at least 10 and no more than 5, so no number can pass."
    fake_claude.script({"envelope": envelope(None, num_turns=4, result=said)})
    gateway = ClaudeGateway(
        mode="live", backend=fake_claude.backend(), store=CassetteStore(tmp_path)
    )

    with pytest.raises(StructuredOutputError, match="Claude said: The form requires") as caught:
        gateway.call(make_request())

    assert caught.value.subtype == "success"
    assert caught.value.metrics is not None
    assert caught.value.metrics.num_turns == 4
    (usage,) = gateway.usage_log  # the failed call's cost is still logged
    assert usage.cost_usd_equivalent == pytest.approx(0.0421)


def test_usage_limit_patterns() -> None:
    assert is_usage_limit("You've hit your weekly Opus limit · resets Mon 9am")
    assert is_usage_limit("You're out of usage credits. /model to switch models.")
    assert is_usage_limit("API Error: 429 rate_limit_error")
    assert not is_usage_limit("Reached max turns (3)")
    assert not is_usage_limit("Failed to provide valid structured output after 5 attempts")


def test_timeout_stops_the_call(fake_claude: FakeClaude, tmp_path: Path) -> None:
    fake_claude.script({"envelope": envelope(VALID), "sleep": 10})
    gateway = ClaudeGateway(
        mode="live", backend=fake_claude.backend(timeout_s=1.0), store=CassetteStore(tmp_path)
    )
    with pytest.raises(ClaudeTimeoutError):
        gateway.call(make_request())


def test_validation_failure_is_retried_once_with_the_problems(
    fake_claude: FakeClaude, tmp_path: Path
) -> None:
    fake_claude.script({"envelope": envelope(WRONG_TOTAL)}, {"envelope": envelope(VALID)})
    store = CassetteStore(tmp_path / "cassettes")
    request = make_request()

    result = ClaudeGateway(mode="live", backend=fake_claude.backend(), store=store).call(request)

    first, second = fake_claude.calls()
    assert first["stdin"] == request.prompt
    assert second["stdin"].startswith(request.prompt)
    assert "total must equal the number of items" in second["stdin"]
    assert result.attempts == 2
    assert result.output == Answer.model_validate(VALID)
    assert [u.request_sha256 for u in result.usage] == [request.request_sha256] * 2
    assert [(u.attempt, u.outcome) for u in result.usage] == [(1, "schema_invalid"), (2, "ok")]
    cassette = store.load(request.request_sha256)
    assert cassette is not None
    assert cassette.attempts == 2
    assert cassette.retry_reason is not None
    assert cassette.request.prompt == request.prompt  # recorded under the original request
    # a replay reports the attempt and turns of the call that recorded the answer
    (replayed,) = ClaudeGateway(mode="replay", store=store).call(request).usage
    assert (replayed.attempt, replayed.num_turns, replayed.outcome) == (2, 2, "ok")


def test_validation_failing_twice_escalates_and_records_nothing(
    fake_claude: FakeClaude, tmp_path: Path
) -> None:
    fake_claude.script({"envelope": envelope(WRONG_TOTAL)})  # every call answers the same
    store = CassetteStore(tmp_path / "cassettes")
    gateway = ClaudeGateway(mode="live", backend=fake_claude.backend(), store=store)

    with pytest.raises(ValidationFailedError, match="escalate"):
        gateway.call(make_request())

    assert len(fake_claude.calls()) == 2
    assert [(u.attempt, u.outcome) for u in gateway.usage_log] == [
        (1, "schema_invalid"),
        (2, "schema_invalid"),
    ]
    assert store.load(make_request().request_sha256) is None


def test_usage_limit_stops_the_run_and_auto_resumes_from_cache(
    fake_claude: FakeClaude, tmp_path: Path
) -> None:
    store = CassetteStore(tmp_path / "cassettes")
    first, second = make_request(prompt="job one"), make_request(prompt="job two")
    fake_claude.script(
        {"envelope": envelope(VALID)},
        {"envelope": envelope(None, is_error=True, result="You've hit your limit"), "exit": 1},
    )
    run1 = ClaudeGateway(mode="auto", backend=fake_claude.backend(), store=store)
    run1.call(first)
    with pytest.raises(UsageLimitError):
        run1.call(second)

    fake_claude.script({"envelope": envelope(VALID)})
    run2 = ClaudeGateway(mode="auto", backend=fake_claude.backend(), store=store)
    assert run2.call(first).replayed
    assert not run2.call(second).replayed
    assert run2.live_calls == 1


def test_live_call_cap(fake_claude: FakeClaude, tmp_path: Path) -> None:
    """
    A call past the cap is refused before ``claude`` starts.
    """
    fake_claude.script({"envelope": envelope(VALID)})
    gateway = ClaudeGateway(
        mode="live", backend=fake_claude.backend(), store=CassetteStore(tmp_path), max_live_calls=1
    )
    gateway.call(make_request())
    with pytest.raises(LiveCallCapError):
        gateway.call(make_request(prompt="another job"))
    assert len(fake_claude.calls()) == 1


def test_live_call_cap_has_no_uncapped_mode(
    fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    A cap of None means D5's default, whether given to the gateway or set on it later.
    """
    monkeypatch.delenv("LANSH_LLM_MAX_LIVE_CALLS", raising=False)
    assert ClaudeGateway().max_live_calls == 150
    monkeypatch.setenv("LANSH_LLM_MAX_LIVE_CALLS", "1")
    fake_claude.script({"envelope": envelope(VALID)})
    gateway = ClaudeGateway(
        mode="live",
        backend=fake_claude.backend(),
        store=CassetteStore(tmp_path),
        max_live_calls=None,
    )
    assert gateway.max_live_calls == 1

    gateway.max_live_calls = None
    gateway.call(make_request())
    with pytest.raises(LiveCallCapError, match="cap of 1 "):
        gateway.call(make_request(prompt="another job"))
    assert len(fake_claude.calls()) == 1


def test_cassette_is_scrubbed(
    fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANSH_TEST_PASSWORD", "not-a-real-secret-42")
    fake_claude.script({"envelope": envelope(VALID)})
    store = CassetteStore(tmp_path / "cassettes")
    request = make_request(prompt=f"see {Path.home()}/x and not-a-real-secret-42")

    result = ClaudeGateway(mode="live", backend=fake_claude.backend(), store=store).call(request)

    text = result.cassette_path.read_text()
    assert "not-a-real-secret-42" not in text
    assert str(Path.home()) not in text
    assert "<redacted:LANSH_TEST_PASSWORD>" in text
    assert str(fake_claude.binary) not in text
    # lookup is by the hash of the real request, so the scrubbed copy still replays
    assert ClaudeGateway(mode="replay", store=store).call(request).replayed


def test_cassette_scrub_finds_a_secret_however_json_escapes_it(
    fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    A secret with a non-ASCII letter and a quote is found in the cassette's UTF-8 JSON.
    """
    secret = 'pässw"rd12'
    monkeypatch.setenv("LANSH_TEST_PASSWD", secret)
    fake_claude.script({"envelope": envelope(VALID)})
    store = CassetteStore(tmp_path / "cassettes")
    request = make_request(prompt=f"sign in with {secret}")

    result = ClaudeGateway(mode="live", backend=fake_claude.backend(), store=store).call(request)

    text = result.cassette_path.read_text(encoding="utf-8")
    assert "<redacted:LANSH_TEST_PASSWD>" in text
    for form in (secret, json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1]):
        assert form not in text
    assert ClaudeGateway(mode="replay", store=store).call(request).replayed


### The smoke test's Claude check and the spike script


def test_smoke_check_gives_claude_the_gateway_environment(
    fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    ``make smoke`` strips the same variables from ``claude``'s environment as the gateway.
    """
    smoke = _load_script(SMOKE_SCRIPT, "lansh_smoke_test")
    monkeypatch.setenv("LANSH_CLAUDE_BIN", str(fake_claude.binary))
    stripped = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDECODE")
    for name in stripped:
        monkeypatch.setenv(name, "1")
    fake_claude.script({"envelope": envelope({"result": 3})})

    assert smoke.claude_code().startswith("7/2 = 3 via the subscription")

    (seen,) = fake_claude.calls()
    assert set(stripped).isdisjoint(seen["env"])
    assert seen["cwd_entries"] == []


def test_smoke_check_reports_how_claude_failed(
    fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    When ``claude`` fails, ``make smoke`` shows its exit code and stderr, not a JSON error.
    """
    smoke = _load_script(SMOKE_SCRIPT, "lansh_smoke_test")
    monkeypatch.setenv("LANSH_CLAUDE_BIN", str(fake_claude.binary))
    fake_claude.script({"stdout": "", "stderr": "Error: not signed in", "exit": 1})

    with pytest.raises(RuntimeError, match="exited with code 1: Error: not signed in"):
        smoke.claude_code()


def test_spike_replay_reads_its_cassette_as_utf8(
    no_subprocess: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The spike replays its recorded answer, reading every file as UTF-8 whatever the locale.
    """
    spike = load_spike()
    read_text = Path.read_text

    def utf8_only(
        self: Path,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> str:
        """
        Read a file as ``Path.read_text`` does, but only when asked for UTF-8.
        """
        assert encoding == "utf-8", f"{self.name} read in the locale's encoding"
        return read_text(self, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "read_text", utf8_only)
    assert spike.replay_only() == 0


def test_spike_effort_probe_reports_a_cli_that_exits_early(
    fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    A CLI that stops before its init event gives an error with its exit code and stderr.
    """
    spike = load_spike()
    monkeypatch.setenv("LANSH_CLAUDE_BIN", str(fake_claude.binary))
    fake_claude.script({"stdout": "", "stderr": "Error: something broke", "exit": 1})

    with pytest.raises(RuntimeError, match="code 1 before its init event: Error: something broke"):
        spike.probe_effort("max")


### One real call (make test-live)


class SevenHalves(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: int


@pytest.mark.live_llm
def test_live_structured_call(tmp_path: Path) -> None:
    """
    One real call on the subscription validates, logs its usage and then replays offline.
    """
    request = ClaudeRequest(
        agent="test_live",
        system_prompt="You answer questions about SQL Server.",
        prompt="In T-SQL, what does SELECT 7/2 return?",
        response_model=SevenHalves,
        effort="low",
    )
    gateway = ClaudeGateway(mode="live", store=CassetteStore(tmp_path), max_live_calls=1)

    result = gateway.call(request)

    assert result.output.result == 3  # integer division truncates (TSQL-03)
    (usage,) = result.usage
    assert not usage.replayed
    assert usage.models_used
    assert usage.cli_version
    assert usage.output_tokens > 0
    assert result.cassette_path.is_file()
    assert ClaudeGateway(mode="replay", store=CassetteStore(tmp_path)).call(request).replayed


### Request hash pin and contract records

# the hash of ``make_request()``, pinned by ``test_request_hash_is_stable``
PINNED_REQUEST_SHA256 = "6166678fa8c0eeef1844954a2488f9d7796d30571edd61befa1670664b695a2d"


def test_contract_records_cannot_be_response_models() -> None:
    from lansh.contracts import LineageEdge

    # records carry factory-owned fields (ids, hashes, decisions) that Claude must never fill in
    with pytest.raises(ValidationError, match="contract record"):
        ClaudeRequest(
            agent="lineage", system_prompt="s", prompt="p", response_model=LineageEdge, effort="low"
        )


def test_subclassed_contract_records_cannot_be_response_models() -> None:
    from lansh.contracts import LineageEdge

    class EdgeAnswer(LineageEdge):
        """
        A contract record under another name, with all its factory-owned fields.
        """

    with pytest.raises(ValidationError, match="contract record"):
        ClaudeRequest(
            agent="lineage", system_prompt="s", prompt="p", response_model=EdgeAnswer, effort="low"
        )


def test_negative_counts_from_the_cli_are_clamped_to_zero() -> None:
    """
    A negative token count or duration can't fail the usage record and hide the outcome.
    """
    from lansh.llm.backend import _int, _opt_int

    assert _int(-3) == 0
    assert _opt_int(-1) == 0
    assert _int(True) == 0
    assert _opt_int(None) is None
