"""Spike 0.4, Claude backend: one structured ``claude -p`` call, recorded, then replayed offline.

The task is a realistic LANSH one: list the T-SQL to Spark traps (plan Appendix A) in a
10-line snippet. The response model nests a list of findings and an enum, so its JSON schema
has ``$defs`` and ``$ref``. Live calls go through ``lansh.llm`` exactly as the factory's will,
and answers are recorded under ``runs/cassettes/spike/``. Findings: ``spikes/README.md``,
"Claude backend".

Usage:
    uv run python spikes/claude_backend.py                        # replay only: no Claude call
    uv run python spikes/claude_backend.py --record               # 1 live call, then replay
    uv run python spikes/claude_backend.py --probe minimal        # 1 live call: smallest request
    uv run python spikes/claude_backend.py --probe unsatisfiable  # 1 live call: impossible schema
    uv run python spikes/claude_backend.py --probe effort-max     # 1 live call: --effort max
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from enum import StrEnum
from pathlib import Path
from typing import Any
from unittest import mock

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lansh.config import RUNS_DIR
from lansh.llm.backend import build_flags, child_env, resolve_binary
from lansh.llm.cassette import CassetteStore
from lansh.llm.errors import ClaudeCallError
from lansh.llm.gateway import ClaudeGateway, ClaudeResult, LLMMode
from lansh.llm.request import ClaudeRequest

SPIKE_CASSETTES = RUNS_DIR / "cassettes" / "spike"

### The realistic request: a trap scan of a 10-line T-SQL snippet


# the response models keep their docstrings exactly as recorded, and this enum has none:
# Pydantic copies a class docstring into the JSON schema, and the schema is part of the hash
# that finds the recorded answer in runs/cassettes/spike/
class TrapKind(StrEnum):
    SEMANTIC = "semantic"
    CONSTRUCT = "construct"


class Finding(BaseModel):
    """One trap occurrence (shaped like ``lansh.contracts.TrapFinding``)."""

    model_config = ConfigDict(extra="forbid")

    trap_id: str = Field(pattern=r"^TSQL-\d{2}$", description="A trap card ID, e.g. TSQL-04.")
    kind: TrapKind
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    snippet: str = Field(min_length=1, description="The code on those lines that sets the trap.")
    confidence: float = Field(ge=0.0, le=1.0)
    note: str = Field(min_length=1, description="One sentence: how Spark's result would differ.")

    @model_validator(mode="after")
    def _ordered(self) -> Finding:
        """
        Refuse a finding whose line range runs backwards.
        """
        if self.line_end < self.line_start:
            raise ValueError("line_end is before line_start")
        return self


class TrapScan(BaseModel):
    """The trap scanner's answer."""

    model_config = ConfigDict(extra="forbid")

    findings: list[Finding]


SYSTEM_PROMPT = """\
You are the trap scanner of LANSH, a factory that migrates legacy T-SQL jobs (SQL Server 2022, \
collation SQL_Latin1_General_CP1_CI_AS) to PySpark 4.2 with ANSI mode on.
A trap is code whose result differs between SQL Server and Spark unless the migration handles it.
Report every trap occurrence in the code you are given, using only these trap cards:
- TSQL-01 (semantic): =, GROUP BY, DISTINCT and joins on strings ignore case under the collation.
- TSQL-02 (semantic): comparisons ignore trailing spaces; CHAR(n) values are space-padded.
- TSQL-03 (semantic): integer division truncates.
- TSQL-04 (semantic): DATEDIFF counts datepart boundaries crossed, not whole elapsed units.
- TSQL-05 (semantic): + concatenation; a NULL operand makes the whole result NULL.
- TSQL-07 (semantic): DECIMAL scale, and ROUND on computed values.
- TSQL-08 (semantic): TOP and TOP WITH TIES.
- TSQL-16 (semantic): CONVERT style codes.
Line numbers are the 1-based numbers at the start of each line. Report one finding per trap \
per occurrence. Don't report code that behaves the same on both engines."""

TSQL_SNIPPET = """\
SELECT c.claim_id,
       c.policy_id,
       DATEDIFF(year, p.inception_date, c.loss_date) AS policy_age_years,
       c.days_open / 30 AS months_open,
       b.broker_code + '-' + c.region AS route_key
FROM stg.claims AS c
JOIN stg.policy_snapshots AS p ON p.policy_id = c.policy_id
LEFT JOIN stg.brokers AS b ON b.broker_id = p.broker_id
WHERE c.status = 'OPEN'
  AND c.reported_date >= '2025-01-01';"""

COLUMN_TYPES = """\
stg.claims: claim_id INT, policy_id INT, loss_date DATE, reported_date DATE, days_open INT, \
status VARCHAR(10), region VARCHAR(20)
stg.policy_snapshots: policy_id INT, inception_date DATE, broker_id INT
stg.brokers: broker_id INT, broker_code CHAR(6)"""


def numbered(code: str) -> str:
    """
    Prefix every line of a code snippet with its 1-based line number.

    The system prompt tells Claude to report these numbers, so findings can be checked against
    the lines where the traps were planted.

    Args:
        code: The snippet, as plain text.

    Returns:
        The same lines, each starting with its number right-aligned in two places.
    """
    return "\n".join(f"{n:>2} {line}" for n, line in enumerate(code.splitlines(), start=1))


def build_request() -> ClaudeRequest[TrapScan]:
    """
    Build the spike's realistic request: a trap scan of the numbered snippet.

    Tests rebuild it to replay the recorded answer, so any change to the prompts, the snippet
    or the response model changes the request hash and leaves the cassette unused.

    Returns:
        The trap-scan request, at effort ``medium``.
    """
    return ClaudeRequest(
        agent="trap_scan",
        system_prompt=SYSTEM_PROMPT,
        prompt=f"Column types:\n{COLUMN_TYPES}\n\nCode:\n{numbered(TSQL_SNIPPET)}",
        response_model=TrapScan,
        effort="medium",
    )


### Investigation probes


# no docstring, for the same reason as TrapKind: it would change the recorded request's hash
class SevenHalves(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: int


class Impossible(BaseModel):
    """No integer satisfies this schema: minimum 10 and maximum 5."""

    model_config = ConfigDict(extra="forbid")

    n: int = Field(ge=10, le=5)


def minimal_request() -> ClaudeRequest[SevenHalves]:
    """
    Build the smallest useful request: what T-SQL's ``SELECT 7/2`` returns.

    Returns:
        A request at effort ``low`` whose answer is a single integer.
    """
    return ClaudeRequest(
        agent="spike_minimal",
        system_prompt="You answer questions about SQL Server.",
        prompt="In T-SQL, what does SELECT 7/2 return?",
        response_model=SevenHalves,
        effort="low",
    )


def unsatisfiable_request() -> ClaudeRequest[Impossible]:
    """
    Build a request that no answer can satisfy, to see how the CLI reports the failure.

    Returns:
        A request at effort ``low`` whose response model accepts no integer at all.
    """
    return ClaudeRequest(
        agent="spike_unsatisfiable",
        system_prompt="You fill in JSON forms.",
        prompt="Return n = 7.",
        response_model=Impossible,
        effort="low",
    )


### Reporting


def show_usage(result: ClaudeResult[Any], wall_s: float | None = None) -> None:
    """
    Print one line per Claude Code invocation behind a result: tokens, time and cost.

    Args:
        result: A gateway result, live or replayed.
        wall_s: Wall-clock seconds measured around the call, if they were measured.
    """
    for u in result.usage:
        print(
            f"  {'replayed' if u.replayed else 'live'}: models {u.models_used}, effort {u.effort}, "
            f"CLI {u.cli_version}, {u.duration_ms} ms, input {u.input_tokens} + cache read "
            f"{u.cache_read_tokens} + cache write {u.cache_creation_tokens} tokens, output "
            f"{u.output_tokens} tokens, ${u.cost_usd_equivalent:.4f} API-equivalent (not billed)"
        )
    if wall_s is not None:
        print(f"  wall clock including claude --version: {wall_s:.1f} s")


def show_cassette(path: Path) -> None:
    """
    Print what a cassette recorded about the CLI's envelope: its keys, timings and usage.

    Args:
        path: The cassette's JSON file.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    response = data["response"]
    keys = response["envelope_keys"]
    print(
        f"  cassette: {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}"
    )
    print(f"  envelope keys ({len(keys)}): {', '.join(keys)}")
    print(
        f"  duration_ms {response['duration_ms']}, duration_api_ms {response['duration_api_ms']}, "
        f"num_turns {response['num_turns']}"
    )
    print(f"  usage: {json.dumps(response['usage'], sort_keys=True)}")
    print(f"  modelUsage: {json.dumps(response['modelUsage'], sort_keys=True)}")


def no_subprocess(*args: object, **kwargs: object) -> None:
    """
    Stand in for ``subprocess.run`` and ``subprocess.Popen`` during a replay.

    Args:
        *args: Ignored.
        **kwargs: Ignored.

    Raises:
        AssertionError: Always, because a replay must never start a process.
    """
    raise AssertionError("replay must not start a subprocess")


def replay(request: ClaudeRequest[TrapScan]) -> ClaudeResult[TrapScan]:
    """
    Answer the trap scan from its cassette with every way of starting a process disabled.

    Args:
        request: The request whose answer was recorded.

    Returns:
        The replayed result.

    Raises:
        CassetteMissingError: If no answer has been recorded for the request.
    """
    gateway = ClaudeGateway(mode=LLMMode.REPLAY, store=CassetteStore(SPIKE_CASSETTES))
    with (
        mock.patch.object(subprocess, "run", no_subprocess),
        mock.patch.object(subprocess, "Popen", no_subprocess),
    ):
        return gateway.call(request)


def record_and_replay() -> int:
    """
    Make the one live trap-scan call, which records its answer, then replay that answer.

    Returns:
        Exit code 0 if the replay came from the cassette and matches the live answer,
        otherwise 1.
    """
    request = build_request()
    print(f"request {request.request_sha256}")
    print(f"schema has $defs: {'$defs' in request.json_schema}")
    gateway = ClaudeGateway(
        mode=LLMMode.LIVE, store=CassetteStore(SPIKE_CASSETTES), max_live_calls=1
    )
    started = time.perf_counter()
    live = gateway.call(request)
    wall_s = time.perf_counter() - started
    print("LIVE")
    show_usage(live, wall_s)
    show_cassette(live.cassette_path)
    for f in live.output.findings:
        print(f"  {f.trap_id} lines {f.line_start}-{f.line_end} ({f.confidence:.2f}): {f.note}")

    replayed = replay(request)
    print("REPLAY (subprocess disabled)")
    show_usage(replayed)
    same = replayed.output == live.output
    print(f"  identical validated output: {same}")
    return 0 if same and replayed.replayed else 1


def replay_only() -> int:
    """
    Replay the recorded trap scan, with no Claude call, and check it against the cassette.

    Returns:
        Exit code 0 if the replayed answer equals the recorded one, or 1 if it differs or no
        answer has been recorded yet.
    """
    request = build_request()
    path = CassetteStore(SPIKE_CASSETTES).path_for(request.request_sha256)
    if not path.exists():
        print(f"no cassette at {path}; run with --record first (one live call)")
        return 1
    result = replay(request)
    recorded = TrapScan.model_validate(
        json.loads(path.read_text(encoding="utf-8"))["response"]["structured_output"]
    )
    print(f"REPLAY of {request.request_sha256} (subprocess disabled)")
    show_usage(result)
    show_cassette(path)
    print(
        f"  {len(result.output.findings)} findings; identical to the cassette: "
        f"{result.output == recorded}"
    )
    return 0 if result.output == recorded else 1


def probe(name: str) -> int:
    """
    Make one live call with the minimal or the unsatisfiable request, and print what came back.

    The unsatisfiable request is meant to fail, so a ``ClaudeCallError`` is printed with the
    metrics the CLI reported instead of being raised.

    Args:
        name: ``minimal`` for the minimal request; any other name means the unsatisfiable one.

    Returns:
        Exit code 0, whether or not the call succeeded.
    """
    request = minimal_request() if name == "minimal" else unsatisfiable_request()
    print(f"probe {name}: request {request.request_sha256}")
    print(f"  --json-schema {json.dumps(request.json_schema, sort_keys=True)}")
    gateway = ClaudeGateway(
        mode=LLMMode.LIVE, store=CassetteStore(SPIKE_CASSETTES), max_live_calls=1
    )
    started = time.perf_counter()
    try:
        result = gateway.call(request)
    except ClaudeCallError as exc:
        wall_s = time.perf_counter() - started
        print(f"  {type(exc).__name__} after {wall_s:.1f} s: {exc}")
        if exc.metrics is not None:
            m = exc.metrics
            print(
                f"  subtype {m.subtype}, is_error {m.is_error}, num_turns {m.num_turns}, "
                f"duration_ms {m.duration_ms}, duration_api_ms {m.duration_api_ms}, "
                f"stop_reason {m.stop_reason}, ${m.total_cost_usd:.4f} API-equivalent"
            )
            print(f"  errors: {list(m.errors)}")
            print(f"  result: {m.result_text!r}")
            print(f"  envelope keys ({len(m.envelope_keys)}): {', '.join(m.envelope_keys)}")
            print(f"  usage: {json.dumps(m.usage, sort_keys=True)}")
            print(f"  modelUsage: {json.dumps(m.model_usage, sort_keys=True)}")
        return 0
    wall_s = time.perf_counter() - started
    print(f"  answer: {result.output.model_dump()}")
    show_usage(result, wall_s)
    show_cassette(result.cassette_path)
    return 0


def probe_effort(level: str = "max") -> int:
    """
    Make one live minimal call at an effort level, and print what the CLI resolved.

    The call uses the gateway's exact flags and environment, but with ``stream-json
    --verbose`` output, whose ``system/init`` event shows the model, effort and credential the
    CLI resolved. It bypasses the gateway, so nothing is recorded.

    Args:
        level: The value to pass to ``--effort``.

    Returns:
        The CLI's exit code.

    Raises:
        RuntimeError: If the CLI stops before its init or result event; the message has its
            exit code and stderr.
    """
    request = minimal_request().model_copy(update={"effort": level})
    flags = build_flags(request)
    at = flags.index("--output-format")
    flags[at + 1 : at + 2] = ["stream-json", "--verbose"]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="lansh-claude-") as empty_dir:
        proc = subprocess.run(
            [resolve_binary(), *flags],
            input=request.prompt,
            capture_output=True,
            text=True,
            cwd=empty_dir,
            env=child_env(),
            timeout=300,
            check=False,
        )
    wall_s = time.perf_counter() - started
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    init = next(
        (e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None
    )
    result = next((e for e in events if e.get("type") == "result"), None)
    if init is None or result is None:
        # a CLI that fails early says why only on stderr
        missing = "init" if init is None else "result"
        raise RuntimeError(
            f"claude exited with code {proc.returncode} before its {missing} event: "
            f"{proc.stderr.strip() or 'nothing on stderr'}"
        )
    shown = ("claude_code_version", "model", "effort", "apiKeySource", "tools", "mcp_servers")
    print(f"probe effort {level}: exit {proc.returncode} after {wall_s:.1f} s")
    print(f"  event types: {sorted({str(e.get('type')) for e in events})}")
    print(f"  init: {json.dumps({k: init.get(k) for k in shown}, sort_keys=True)}")
    print(f"  stderr: {proc.stderr.strip() or '(empty)'}")
    usage = next(iter(result.get("modelUsage", {}).values()), {})
    print(
        f"  result: subtype {result.get('subtype')}, is_error {result.get('is_error')}, "
        f"structured_output {result.get('structured_output')}, "
        f"duration_ms {result.get('duration_ms')}, output {usage.get('outputTokens')} tokens "
        f"(thinking {usage.get('thinkingTokens')}), ${result.get('total_cost_usd', 0):.4f}"
    )
    return proc.returncode


def main() -> int:
    """
    Replay the recorded answer, or make the one live call that the flags ask for.

    Returns:
        The exit code of whichever action ran.
    """
    # the description is the module docstring's first line, which is why that docstring keeps
    # its summary on the opening quotes' line instead of following the house layout
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--record", action="store_true", help="one live call, then replay")
    group.add_argument(
        "--probe", choices=["minimal", "unsatisfiable", "effort-max"], help="one live call"
    )
    args = parser.parse_args()
    if args.record:
        return record_and_replay()
    if args.probe == "effort-max":
        return probe_effort("max")
    if args.probe:
        return probe(args.probe)
    return replay_only()


if __name__ == "__main__":
    sys.exit(main())
