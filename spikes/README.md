# Phase 0 spikes

The four spikes were plan step 0.4. Each one tested a risky part of the stack on the real engines so that Phase 2 can build on it, and all four passed. This file keeps what they found: the verdicts and evidence, every gotcha, and the decisions Phase 2 inherits.

**SQL Server** has no section of its own, because its spike lives on in [compose.yaml](../compose.yaml) and [src/lansh/engines/mssql.py](../src/lansh/engines/mssql.py). SQL Server 2022 (16.0.4305.5) runs under compose with collation `SQL_Latin1_General_CP1_CI_AS`. The image is pinned by digest, and the SA password comes from `.env`. The adapter deploys scripts split on `GO`, calls procedures, reads whole tables into Arrow with exact types, and loads Arrow tables through multi-row `INSERT` statements with literal values, so nothing passes through a float. Typed reads and writes round-trip exactly: fadas, trailing spaces, `''` against NULL, CHAR padding, decimals, `DATETIME2(6)` and bigints beyond 2^53. `code = 'MOT'` matches `'MOT '`, `'mot'` and `'Mot'`, which confirms the case- and space-insensitive collation.

To re-run a spike, from the repo root:

```bash
make legacy-up && make test-mssql        # SQL Server: healthy in about 7 s, then the exact round trip
uv run python spikes/spark_recon.py      # Spark: offline, about 17 s
uv run python spikes/claude_backend.py   # Claude: replays the recorded answer, no live call
uv run python spikes/sas_roundtrip.py --out /tmp/sas-spike   # SAS: one OnDemand session, about 65 s
```

## Spark reconciliation

> **Step 2.1 (12 Nov):** the engine now lives in [src/lansh/reconcile/engine.py](../src/lansh/reconcile/engine.py), with the decisions below applied. `spark_recon.py` keeps the planted tables and the demonstration, run against that engine, and its tests guard the engine.

**Works.** Spark 4.2's collations find the planted case and trailing-space differences, and absorb them inside the comparison. NULL against a value is still reported, and NULL against NULL never is. Everything written is a plain string, and datacompy agrees with the `exact` result.

- **Prototype:** [spark_recon.py](spark_recon.py), with 22 tests in [tests/test_spark_recon_spike.py](../tests/test_spark_recon_spike.py) (marked `spark`, run in the default suite).
- **Versions:** PySpark 4.2.0, delta-spark 4.4.1, Java 21.0.13, Python 3.14.7, pandas 2.3.3, datacompy 1.2.0. The session is always `lansh.spark.get_spark()`: Delta on, time zone UTC, ANSI on.
- **What it does:** `compare()` runs the checks of plan §8.6 in order: schema, counts (in total and per partition), totals, key integrity, a full outer join on the keys, a comparison of each column under its policy, and a status for every row. It returns `lansh.contracts` models plus the lazy per-row frame, and `ReconResult.to_report()` builds a valid `ReconReport`. `contracts.py` was not changed.

| Policy | How it compares (NULL always equals NULL) |
|---|---|
| `exact` | `l <=> r`. Numbers compare by value, so `decimal(10,2)` 100.10 equals `decimal(10,1)` 100.1. Other type mismatches compare as text |
| `ci_rtrim` | `collate(·,'UTF8_LCASE_RTRIM')` on both sides, then `<=>`. Works on keys too |
| `rtrim` | `collate(·,'UTF8_BINARY_RTRIM')`: case-sensitive, trailing spaces ignored |
| `blank_is_null` | `nullif(rtrim(·),'')`: a SAS blank counts as missing |
| `float_rel(tol)` | `l <=> r`, or both values finite and `abs(l-r) <= tol*greatest(abs(l),abs(r))` |
| `exclude`, `surrogate` | Neither compared nor totalled |

### What the planted tables show

Legacy has 11 rows and the candidate 12. The contract policies are `ci_rtrim` on the key and text columns, `float_rel` 1e-9 on `loss_ratio`, and `exclude` on the load timestamp `loaded_at`.

| Planted case | Every column `exact` | Contract policies |
|---|---|---|
| `status` 'Open' vs 'OPEN'; `product` 'MOT ' vs 'MOT' | found (1 each) | absorbed |
| `region` NULL vs 'X' | found | **still found** |
| NULL vs NULL in `region`, `premium` and `loss_ratio` | not counted | not counted |
| `premium` 100.10 `decimal(10,2)` vs 100.1 `decimal(10,1)` | equal; the schema check reports the type | the same |
| `loss_ratio` 1e-12 and 1e-6 relative | both found | 1e-12 passes, 1e-6 still found |
| key 'POL-012' vs 'pol-012' | missing + extra | matched |
| POL-009 only in legacy, POL-010 only in the candidate | missing, extra | the same |
| POL-011 twice in the candidate | `candidate_duplicate_keys=1`; match + extra | the same |
| `loaded_at` | differs on all 9 common rows | excluded |
| **Rows** | **matched 0, value_diff 9, missing 2, extra 3** | **matched 8, value_diff 2, missing 1, extra 2** |

- **datacompy** (`abs_tol=0, rel_tol=0`) agrees with the `exact` run on every measure: 9 rows in common, 2 only in legacy, 3 only in the candidate, 0 fully matching rows, and the same mismatch count in each of the 6 columns (`status` 1, `product` 1, `region` 1, `premium` 0, `loss_ratio` 2, `loaded_at` 9).
- **Delta.** A collated column (`string collate UTF8_LCASE_RTRIM`) can't be written to Delta; after `plain_strings()` it writes, and it reads back with the same statuses: `{'match': 8, 'value_diff': 2, 'extra': 2, 'missing': 1}`. The per-row result itself reports each key as given (legacy's value, or the candidate's for an extra row), not the normalised form used for matching.

### Gotchas (each one reproduced)

1. **Collations work with `eqNullSafe`/`<=>`.** `collate(l,C) <=> collate(r,C)` is true for 'Open'/'OPEN', 'MOT '/'MOT' and NULL/NULL, and false for NULL/'X'. Plain `=` returns NULL whenever either side is NULL, so always use `<=>`, and wrap the result in `coalesce(…, false)`.
2. **Collated join keys are rewritten, not compared byte by byte.** The full outer join plan is `SortMergeJoin [coalesce(collationkey(_lk0), 0x), isnull(collationkey(_lk0)), _ldup], […], FullOuter`, and a broadcast hash join is rewritten the same way. GROUP BY and window `partitionBy` and `orderBy` follow the collation too: 'A' and 'a ' fall in one group, and 'apple' sorts before 'Banana'. A test checks that the plan still contains `collationkey`, so a Spark upgrade that drops the rewrite fails loudly.
3. **Collations are part of the type, so they spread and they clash.** A collated column `=` a plain one fails with `[INDETERMINATE_COLLATION_IN_EXPRESSION]`, and two different explicit collations fail with `[COLLATION_MISMATCH.EXPLICIT]`. `collate()` on one side only silently applies to both. Worst of all, an input column that's already collated makes `=` against a literal case-insensitive without saying so. So `compare()` strips collations from its inputs after the schema check, and a test proves that `exact` stays binary.
4. **Delta refuses collated types at any depth**, inside `array<…>` and `struct<…>` too: `[DELTA_UNSUPPORTED_DATA_TYPES] Found columns using unsupported data types: [policy_id: StringType(UTF8_LCASE_RTRIM)]`. The message suggests setting `spark.databricks.delta.schema.typeCheck.enabled=false`. **Never do that.** `cast("string")` drops the collation, and `plain_strings()` does it recursively.
5. **Parquet doesn't refuse them.** A collated column written to Parquet reads back as `string collate UTF8_LCASE_RTRIM`, so the golden typed Parquet (§7.3) needs `plain_strings()` too.
6. **RTRIM trims spaces only.** 'A\t' doesn't equal 'a', and nor does 'A' followed by a no-break space. This matches SQL Server, which pads with spaces only.
7. **Decimal totals under ANSI.** `sum(decimal(p,s))` returns `decimal(min(38,p+10),s)`, and on overflow it fails with `[NUMERIC_VALUE_OUT_OF_RANGE.WITH_SUGGESTION] … cannot be represented as Decimal(38, 2). If necessary set "spark.sql.ansi.enabled" to "false"`. Never turn ANSI off. `try_sum` returns NULL instead, which a count of non-NULL values turns into a reported error (tested). `sum(bigint)` fails with `[ARITHMETIC_OVERFLOW]`, so integers are summed as `decimal(38,0)`.
8. **Decimal scale.** The legacy total comes back from Spark as `2261.10` and the candidate total as `2261.1`. Canonical text (`Decimal.normalize`) makes both `'2261.1'`.
9. **Totals can agree while rows differ.** The planted premium totals match exactly: the missing 300.00 against the extra 150.0 + 150.0. Only the row-level checks catch that.
10. **Spark's NaN rules break a naive relative tolerance.** In Spark, NaN = NaN is true and NaN sorts above everything, so a bare `abs(a-b) <= tol*greatest(abs(a),abs(b))` says NaN equals 1.0 and inf equals 1e308. The tolerance branch therefore requires both values to be finite, and a test covers 9 cases.
11. **Under ANSI, a key whose type differs between the sides fails the join.** `int_col <=> string_col` fails with `[CAST_INVALID_INPUT] The value 'x' of the type "STRING" cannot be cast to "BIGINT"`. Such keys, and value columns, are compared as text, and the schema check reports the mismatch.
12. **datacompy can only cross-check `exact`.** Its `ignore_case` is never applied to join columns, so 'POL-012'/'pol-012' stay split even with `ignore_case=True, ignore_spaces=True`. `ignore_spaces` is `str.strip()`, which removes leading as well as trailing whitespace, tabs and newlines included, and `ignore_case` is `str.upper()`, which has the 'ß' problem of gotcha 15. It turns `Decimal` into float, so it can't tell decimals apart beyond about 15–17 significant digits, and it pairs duplicate keys in frame order (`cumcount`).
13. **Pairing duplicates.** Ordering duplicates by their raw values pairs the wrong rows under `ci_rtrim`: in binary order 'Banana' < 'apple', but 'APPLE' < 'banana'. Ordering them by the policy-normalised values fixes it, and a test covers this.
14. **Partition counts must use the column's policy.** Under `exact`, 'MOT ' is a separate partition (legacy 1, candidate 0). Under `ci_rtrim` it merges with 'MOT' (5 against 6).
15. **Unicode case folding.** `upper()` makes 'ß' equal 'SS' and 'ı' equal 'I'; `UTF8_LCASE_RTRIM` and `lower()` don't. The Irish fadas ('SEÁN'/'Seán ', 'Ó Briain'/'ó briain') and Greek sigma agree under all three.
16. **Timing.** The session starts in 4.2 s (Ivy cache warm); one `compare()` on about 12 rows takes 1.5–2.1 s, which is 4–5 Spark actions (two side aggregates, partition counts, the joined aggregate, and a samples query only when something differs); the first Delta write and read in a JVM takes about 5 s; the demo runs in 17.2 s and the 22 tests in 22.2 s.

### Decisions for step 2.1

1. **Collations live only inside `normalise()` and `values_equal()`.** Inputs are stripped of collations on entry, after the schema check has seen the raw types. Every DataFrame the engine returns or writes goes through `plain_strings()`, and a check refuses collated types before any write, to Delta or Parquet. Unlike this prototype, whose per-row frame keeps collated keys, the 2.1 engine returns plain strings at its boundary.
2. **Join on the policy-normalised keys plus a duplicate number,** with `<=>`. The number is `row_number()` within each key, ordered by the normalised values, so duplicates become extra or missing rows instead of multiplying the join (datacompy's approach too). Keys may be `exact`, `ci_rtrim`, `rtrim` or `blank_is_null`; `float_rel`, `exclude` and `surrogate` are refused on keys. With no keys, compare as multisets, joined on every compared column: `float_rel` then acts as `exact`, and a warning is logged.
3. **Policy semantics as in the table above.** `float_rel` keeps the finiteness guard. `exclude` and `surrogate` columns are neither compared nor totalled.
4. **A different decimal precision or scale is a schema mismatch,** not a value difference; values still compare by number. The job template (2.6) casts outputs to the contract types.
5. **Totals.** Integers and decimals: exact sums as canonical `DecimalText`, with `try_sum` plus a non-NULL count, so an overflow becomes an explicit error with status `ERROR`. Doubles: summed as double and compared under the column's policy. Exact double totals can depend on summation order on big data, so 2.1 should compare them under `float_rel`, or sum `cast(x as decimal(38,18))`.
6. **`KeyIntegrity` counts distinct duplicated key values per side,** not surplus rows. Surplus rows already show up as `extra` or `missing`.
7. **Status strings** are `match`, `value_diff`, `missing` and `extra`, the same names as the `RowCounts` fields.
8. **Samples.** At most 5 per differing column, from one window query. Masking `pii` columns (§8.6 data minimisation) is 2.1's job and isn't in this spike.
9. **Cross-check.** The "datacompy agrees" test in 2.1 uses `exact` policies with `abs_tol=0, rel_tol=0`, comparing rows in common, rows only in each side, matching rows and per-column mismatches. The engine's own unit tests cover policy semantics.
10. **Performance.** One aggregate per check, about 5 actions per comparison, and one shared Spark session per test run.

### Decided fallback

**If collations misbehave, normalise into plain strings instead: `lower(rtrim(x))` for `ci_rtrim` and `rtrim(x)` for `rtrim`.** Misbehaving means, for example, that a Spark or Databricks runtime drops the `collationkey` join rewrite, that a collated plan errors or is slow, or that a target can't use collations.

- It's already built in: `compare(..., use_collations=False)`. On the planted data it gives identical row counts and per-column mismatches, with no `collationkey` in its join plan (`test_fallback_without_collations_gives_the_same_result`), and it agrees with the collation on every Unicode probe (`test_fallback_agrees_with_the_collation_on_unicode_text`).
- **Why `lower` and not `upper`:** UTF8_LCASE is defined by lower-casing, and `upper(rtrim())` would also make 'ß' equal 'SS' and 'ı' equal 'I', which the collation doesn't (gotcha 15).
- The cost: the join and GROUP BY run on a computed column instead of a collation key. Delta is unaffected, because everything is a plain string either way.

### Open points

- SQL Server's own answers for 'ß', 'ı' and accented ordering haven't been checked against the container. Our synthetic data is ASCII plus Irish fadas, where every method agrees. Ordering under `UNICODE_CI_RTRIM` (trap TSQL-19) wasn't part of this spike.
- Pairing duplicates is deterministic, but it isn't an optimal match: duplicates whose values differ in several columns can still pair badly. That's rare, and `KeyIntegrity` flags them anyway.

## Claude backend

**Works.** One structured `claude -p` call with the full flag set of plan §8.2 ran on our subscription. It was recorded as a cassette and then replayed offline, with identical validated output and no subprocess started. The code is the seed of the Claude gateway (step 2.2) in `src/lansh/llm/`.

- **Run** on 10 Nov 2026 with Claude Code 2.1.311 (`/opt/homebrew/bin/claude`). `--model opus` resolved to `claude-opus-5-5`.
- **Sign-in:** the subscription. The `stream-json` init event reported `apiKeySource: "none"`.
- **Live calls:** 6 in total (the cap was 6), about $0.10 API-equivalent in all, not billed.
- **Re-run:** the spike replays by default. `--record` and `--probe minimal|unsatisfiable|effort-max` make one live call each. `uv run pytest tests/test_llm_gateway.py` runs offline, and `-m live_llm` runs its one live test.
- **Built** (each module's docstring has the detail):
  - `request.py`: `ClaudeRequest`, and the canonical request hash.
  - `backend.py`: `ClaudeCodeBackend`, which builds the exact argv, strips the child environment, runs the call in an empty temporary folder with a timeout, parses the envelope and maps failures to exceptions.
  - `cassette.py`: `Cassette` and `CassetteStore`, one JSON file per request hash in `runs/cassettes/`, scrubbed before it's written so it's safe to commit.
  - `gateway.py`: `ClaudeGateway`, with the `live`, `replay` and `auto` modes, the Pydantic re-check with one retry, an `LLMUsage` record per call, and the live-call cap (D5).
  - `errors.py`: `UsageLimitError`, `StructuredOutputError`, `ValidationFailedError`, `CassetteMissingError`, `LiveCallCapError` and others.
  - `runs/cassettes/spike/`: the two recorded answers, the trap scan (`b4865c7b…`) and the minimal call (`aa473335…`).

### Flags confirmed

Every call uses exactly this argv. The prompt goes on **stdin**, never in argv.

```text
claude -p --output-format json --json-schema <schema> --system-prompt <text> --model opus
       --effort <level> --tools "" --setting-sources "" --no-session-persistence --strict-mcp-config
```

| Flag | Evidence |
|---|---|
| `-p --output-format json` | One JSON result object on stdout in all six calls |
| `--json-schema` | Pydantic's schema went in as compact JSON with `$defs`, `$ref` and enums kept, and the validated answer came back in `structured_output` |
| `--system-prompt` | It replaces Claude Code's default prompt: the whole minimal call came to 1,098 input tokens |
| `--model opus` | The `modelUsage` key and the init `model` were both `claude-opus-5-5` |
| `--effort` | `low`, `medium` and `max` were used live with no warning (finding 2) |
| `--tools ""` | The init event listed `tools: ["StructuredOutput"]`: no built-in tools, only the one `--json-schema` adds |
| `--setting-sources ""` | No user settings or plugins were loaded |
| `--strict-mcp-config` | The init event listed `mcp_servers: []` |
| `--no-session-persistence` | Nothing is saved, so nothing can be resumed |
| `--bare` | Never used. A test asserts it's absent from argv and from recorded flags |

Sending the prompt on stdin worked in all six calls. It also avoids three problems: `--tools <tools...>` is variadic, so it would swallow a positional prompt placed after it; argv has a size limit; and prompts in argv are visible in `ps`.

### The JSON envelope (Claude Code 2.1.311)

- A successful structured call has **27 keys**: `api_error_status`, `duration_api_ms`, `duration_ms`, `fast_mode_disabled_reason`, `fast_mode_state`, `first_content_frame_ms`, `is_error`, `modelUsage`, `num_turns`, `permission_denials`, `queued_turn_count`, `result`, `result_index`, `safety_stops`, `session_id`, `stop_reason`, `structured_output`, `subagent_stats`, `subtype`, `terminal_reason`, `time_to_request_ms`, `total_cost_usd`, `ttft_ms`, `ttft_stream_ms`, `type`, `usage`, `uuid`.
- When Claude can't satisfy the schema, the envelope has the same keys minus `structured_output`, so 26.
- According to the CLI's own result schema, error results (`subtype` `error_during_execution`, `error_max_turns`, `error_max_budget_usd` or `error_max_structured_output_retries`) add `errors: string[]`. None was observed live.
- `usage` is cumulative over all turns, but its `iterations` list only holds the last API request.
- `modelUsage` has one entry per model, with `inputTokens`, `outputTokens`, `cacheReadInputTokens`, `cacheCreationInputTokens`, `thinkingTokens`, `costUSD`, `contextWindow` (1,000,000), `maxOutputTokens` (128,000), `provider` (`firstParty`) and `costBasis` (`list`). The gateway takes tokens from the `modelUsage` sums, and `models_used` from its keys.
- A structured answer always costs 2 turns: the tool call and its result.

### The calls

- **Time and tokens.** The minimal call ("what does `SELECT 7/2` return?", effort `low`) took 2.6 s of wall time: 1.6 s of `duration_ms` in the CLI, plus about 1 s of CLI start-up and exit. It used 1,098 input tokens, all written to the prompt cache, and 51 output tokens. The trap scan (effort `medium`) took 10.8 s, and each unsatisfiable probe about 8 s.
- **Caching.** Claude Code caches the system prompt and the tool schema with a **1-hour TTL** (`ephemeral_1h_input_tokens`), and calls made within the hour read that cache back: the first unsatisfiable probe read 3,810 cached tokens.
- **The trap scan** found exactly the six planted traps: TSQL-04 `DATEDIFF(year, …)` on line 3; TSQL-03 `days_open / 30` on line 4; TSQL-05 `+` concatenation with a NULL from the LEFT JOIN, and TSQL-02 CHAR(6) padding in that concatenation, on line 5; TSQL-01 the case-insensitive `status = 'OPEN'`, and TSQL-02 trailing spaces in that comparison, on line 9.

### Findings

1. **`--json-schema` accepts Pydantic schemas with `$defs`, `$ref` and enums as they are.** The trap scan sent `TrapScan → list[Finding]` with a `TrapKind` enum, all through `$defs` and `$ref`. The CLI and Pydantic both validated the answer, and the replay was identical. Inlining isn't needed, so it isn't implemented.
2. **Effort levels.**
   - Claude Code 2.1.311 accepts `low`, `medium`, `high`, `xhigh` and `max`, plus the alias `med`. It also accepts `ultracode`, a separate special mode that maps to `xhigh` (`ma=["low","medium","high","xhigh","max"]` in the CLI source).
   - **An unknown level isn't rejected.** The parser prints `Unknown --effort value '…' — ignoring it and using the default effort` to stderr, and the call goes ahead (CLI source, function `Pvt`). The gateway therefore checks the level itself: `Effort` is a `Literal`, and a test covers it.
   - For opus, calls at `low`, `medium` and `max` gave no warning. On the same prompt, thinking went from 0 tokens at `low` to 111 at `max`.
   - The CLI silently downgrades `max` and `xhigh` to `high` on models that don't support them. It asks its model catalogue first, then falls back to hard-coded lists: `max` is unsupported on `claude-3-*`, Opus 4.0, 4.1 and 4.5, Sonnet 4.0 and 4.5, and Haiku 4.5, and `xhigh` on those plus Opus 4.6 and Sonnet 4.6. Opus 5.5 is on neither list, so it gets all five levels.
   - **Limitation:** neither the envelope nor the init event reports the effective effort (the init `effort` was `null`), so a silent downgrade can't be seen from outside.
3. **`CLAUDE_CODE_EFFORT_LEVEL` overrides `--effort`.** In the CLI source, the environment value is used first and the flag only after it. The gateway strips that variable.
4. **Calls made from inside a Claude Code session inherit its variables**, such as `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_CODE_ENTRYPOINT` and a messaging socket and token. With them set, the child treats itself as a child session (CLI source, function `tjt`). The gateway therefore gives `claude` the parent environment minus every `ANTHROPIC_*` and `CLAUDE_CODE_*` variable except `CLAUDE_CODE_OAUTH_TOKEN` (headless sign-in), and minus `CLAUDECODE`, `CLAUDE_PID`, `CLAUDE_EFFORT`, `CLAUDE_AGENT_SDK_VERSION`, `AI_AGENT`, `MCP_CONNECTION_NONBLOCKING`, `MAX_THINKING_TOKENS`, `MAX_STRUCTURED_OUTPUT_RETRIES` and `MSSQL_SA_PASSWORD`. `ANTHROPIC_API_KEY` is always gone, and a test checks the environment the fake `claude` received.
5. **An unsatisfiable schema still reports success.** We sent `n` with `minimum 10` and `maximum 5`, twice. Both times Claude called the structured-output tool twice, the CLI's validator rejected it both times, and Claude then gave up and explained in prose: "The form requires `n` to be at least 10 and also no more than 5, so no number can ever pass…". The CLI still reported `subtype: "success"` and `is_error: false`, with `num_turns: 4`, `stop_reason: "end_turn"` and **no `structured_output` key**, after about 7.5 s and $0.016–0.022. It did **not** return `error_max_structured_output_retries`, which comes only once the internal retries run out (`MAX_STRUCTURED_OUTPUT_RETRIES`, default 5). **So `subtype` and `is_error` alone can't be trusted.** The gateway requires a `structured_output` object, raises `StructuredOutputError` without one whatever `subtype` says, quotes Claude's own words, and still logs the call's cost.
6. **Usage limits.** The CLI source words them as "You've hit your … limit · resets …", "You're out of usage credits", "… spend limit", "shared budget", "usage limit reached", or in older versions "Claude AI usage limit reached|\<epoch\>". The gateway looks for them in `result`, `errors` and stderr, and raises `UsageLimitError` with a hint of when the limit resets. Every validated answer is written to its cassette as soon as it arrives, so a run stopped by a limit resumes in `auto` mode from where it stopped (tested with a fake `claude`). No limit was hit live.
7. **`stream-json --verbose` also emits a `rate_limit_event`.** It could warn us before the limit is reached. It isn't used yet.
8. **The ~700-token context in plan §6.7 doesn't match our flag set.** With `--system-prompt` and `--json-schema`, the minimal call used 1,098 input tokens.

### Decisions taken in this spike

- **The default mode is `replay`** (`LANSH_LLM_MODE` unset). Nothing can spend subscription quota unless someone opts in, and the offline tests and `make demo` need no Claude access. A missing answer fails loudly (`CassetteMissingError`, which says how to record the answer) instead of silently becoming a live call. `.env.example` documents `replay`, development runs that need new answers set `auto`, and the test module forces `replay` whatever `.env` says.
- **The request hash** is SHA-256 over the canonical JSON (sorted keys, compact, UTF-8) of the model, effort, system prompt, prompt and JSON schema. The agent and job are labels, so they aren't part of the hash. CRLF line endings are normalised to LF before sending and hashing; nothing else in the text changes, because trailing spaces are data. A test pins the hash of a fixed request: a failure there means every recorded answer would stop matching.
- **Cassettes** are `runs/cassettes/<sha256>.json`, written atomically with sorted keys. Each holds the request; the recorded flags, with the two long values shown as `<system_prompt>` and `<json_schema>`; the validated `structured_output`, `usage`, `modelUsage`, `total_cost_usd`, `duration_ms`, `duration_api_ms`, `num_turns` and envelope keys; the number of attempts; the CLI version; and the time it was recorded. None of these is stored: the binary path, the working folder, the environment, `session_id`, `uuid`. Before writing, the store replaces the value of every variable named like a password, token, secret or key, the repository path and the home folder.
- **Usage accounting:** one `LLMUsage` per live `claude -p` invocation, so a retry makes two, and one per replay, with `replayed=True`. `models_used` comes from the `modelUsage` keys. A failed live call is logged whenever the CLI reported metrics.
- **Validation:** Claude Code checks the schema, then Pydantic re-checks the answer. On a Pydantic failure, the gateway retries once, quoting the problems back to Claude. If that fails too, it raises `ValidationFailedError` (escalate). A recorded answer that no longer validates raises an error in `replay` and is re-recorded in `auto`.
- **`max_live_calls`** caps a run's live calls (D5) and raises `LiveCallCapError` before the call.

### Decided fallback

- **If structured output through `--json-schema` breaks in a later CLI:** keep Claude Code at 2.1.311 while we investigate; replay keeps the demo working throughout. Then drop `--json-schema`, put the schema in the system prompt and parse JSON from `result`, keeping the same Pydantic re-check, single retry and cassette format. Only `build_flags` and `parse_result` change.
- **If a later CLI rejects `$ref`:** inline the `$defs` before sending.
- **If the subscription route itself is unavailable** (usage limits or sign-in): runs stop cleanly and resume from cassettes, and Sonnet takes the bulk steps (D4). An API-key backend stays Tier 3. It needs a team decision and is never a default.

### Open points

- Found when the spike was verified, for step 2.2 ([G1 packet](../docs/gates.md#gate-1-foundations)): the usage-limit detector also matches "Context limit reached", and a usage-limit message inside a non-error result isn't detected.

## SAS round trip

**Works, with one correction to the plan.** A saspy round trip through SAS OnDemand, with explicit informats on the way in and explicit formats on the way out, returns every value SAS can hold **bit for bit**, but only because the export also writes `HEX16.`. The plan's assumption that `BEST32.` has "enough digits to round-trip a double" was wrong: it keeps at most 15 significant digits. §7.3 is now corrected. The engine is [src/lansh/engines/sas.py](../src/lansh/engines/sas.py), which step 1.6 (golden capture) reuses; its docstring sets out the CSV dialect, the informats and the formats.

- **SAS:** 9.04.01M9P06052025 (9.4M9) on SAS OnDemand, Linux, session encoding `utf-8`. Options found: `NONOTES` (gotcha 2), `VALIDVARNAME=ANY` and `MISSING=.`.
- **Client:** saspy 5.110.0 (IOM), Java 21, Python 3.14.7, pandas 2.3.3, pyarrow 26.0.1. Run on 10 Nov 2026, with one SAS session at a time, always ended.
- **Re-run:** the spike prints a value-by-value comparison and ends with `PASS: every value matches SAS semantics exactly via HEX16.` It writes the CSVs, the PROC CONTENTS metadata, the redacted SAS log (`sas.log`) and `summary.json` to `--out`, and its remote files to `~/lansh/spike/` on the SAS server. Every log is redacted (the home directory becomes `~` and the user ID `<user>`): in the final run, `grep -c -E '/home/u[0-9]'` found 0 matches in `sas.log` and `summary.json`. `uv run pytest tests/test_sas_engine.py` runs the offline tests in under 1 s, and `-m sas` the live round trip in about 25 s.
- **Built:** `SasSession`, a context manager that always ends the session (after an error or a failed start too), turns notes on, keeps every step's redacted log and raises `SasError` when the log has an error; the code generators `read_step`, `export_step` and `contents_step`, all tested offline; and on the Python side `write_input_csv`, `parse_export`, and `upload_table` and `export_table` for the whole trip in one call each (`upload_table` checks the row count and treats read problems as fatal). `parse_export` cross-checks the formatted text against `HEX16.` and types each column from the PROC CONTENTS metadata: `char` becomes `string`, a number with a date format `date32[pyarrow]`, a number with a datetime format `datetime64[us]`, and any other number `float64`.

### Planted round trip: 20 rows, 11 columns

The DATA step was `total = sum(a, b); plus = a + b;`. "Exact" means the values were read from the `HEX16.` sidecar. "Text only" means the same export was read from its `BEST32.` and `E8601DT26.6` text alone.

| Column | Exact (`HEX16.`) | Text only | What text alone lost |
|---|---|---|---|
| `_row_seq` | 20/20 | 20/20 | nothing (physical order was `_row_seq` order) |
| `int_val` | 20/20 | 20/20 | nothing; ±2**53 and 2**53−1 are exact |
| `money` (2 dp) | 20/20 | 19/20 | `123456789012345.68` became `123456789012345`: the cents were dropped |
| `dbl` | 20/20 | **8/20** | `0.1+0.2`→`0.3`, `1/3`→`0.33333333333333`, `π`→`3.14159265358979`, `1+2**-52`→`1`, `-0.0`→`0`, `9.999999999999998`→`10`, … |
| `a`, `b` | 20/20 | 18/20, 19/20 | the sign of `-0.0` |
| `d` (date) | 20/20 | 20/20 | nothing |
| `ts` (datetime) | 20/20 | 19/20 | `1939-06-07T13:48:03.939733` printed as `.939734` |
| `s` (text) | 20/20 | 20/20 | nothing (text never goes through `BEST32.`) |
| `total`, `plus` | 20/20 | 14/20 | `0.30000000000000004`→`0.3`, `0.7999999999999999`→`0.8`, `123.46000000000001`→`123.46`, … |

**Exact, compared bit for bit** (doubles through their IEEE bits, so `-0.0` is not `0.0`):

- **Integers:** 0, ±1, 42, 2**31−1, −2**31, 2**53−1, ±2**53, 10**15, 2**40, 65535, −65536.
- **Money:** `0.00`, `0.10`, `0.20`, `0.30`, `-0.01`, `-0.10`, `0.07`, `-1234.56`, `1234567.89`, `99999999.99`, `1234567890123.45` (15 significant digits).
- **Doubles:** those needing 17 digits (`0.1+0.2`, `1/3`, `2/3`, π, e, `1+2**-52`, `123456789.12345678`, `3000000000.0000005`, `0.12345678901234568`), and `-0.0`, `1e-300`, `1e300`, `4.35`. Missing numbers: NULL in, missing out.
- **Dates:** 1960-01-01 (SAS 0), 1959-12-31 (SAS −1), 2024-02-29, 2025-12-31, 1582-01-01, 1582-10-15, 2100-03-01, 9999-12-31.
- **Datetimes:** whole seconds, `.123456`, `.999999`, 1959-12-31T23:59:59.5, 2120-01-01T00:00:00.000001.
- **Text:** `"  leading"` (leading blanks kept), `has,comma`, `has "quote"`, `"starts with a quote`, `O'Brien`, `Seán Ó Briain`, `Siobhán`, `ÁÉÍÓÚ áéíóú`, `€100`, `tab<TAB>here`, a lone `.`, `007`, and a 200-character string with fadas. That last one is 220 bytes, so SAS gave the column length `$220`: SAS lengths are bytes, not characters.

**Changed, because SAS has no way to hold them** (each is the correct SAS semantics):

| Original | Back from SAS | Why |
|---|---|---|
| `'trailing  '` | `'trailing'` | SAS values are blank-padded, so trailing blanks can't be told apart from padding |
| `' both '` | `' both'` | the same; the leading blank is kept |
| `''` (empty string) | NULL | **SAS has no empty string**: a blank character value *is* missing |
| `'   '` (blanks only) | NULL | the same |
| `123456789012345.68` | `123456789012345.69` | 17 significant digits; the nearest double prints as `.69`. The writer warns about any decimal with more than 15 significant digits |

**SAS semantics confirmed:**

- `sum(1, .)` = 1, `sum(., 2)` = 2 and `sum(., .)` = missing.
- `a + b` with a missing operand is missing, and the log says *"Missing values were generated as a result of performing an operation on missing values."*
- `sum(0.1, 0.2)` and `0.1 + 0.2` are both `3FD3333333333334`, identical to IEEE 754 in Python. `1e16 + 1 = 1e16`, and `sum(-0, -0) = -0`, as in Python.

### Bulk probe: 4,016 values, seed 20261110

The probe uploaded each value's text, read it in SAS with `x = input(txt, ?? BEST32.)`, and exported the result.

| Kind | Rows | Read exactly by SAS | Unreadable | `BEST32.` text exact |
|---|---|---|---|---|
| money: 2 dp, up to 13 integer digits | 1000 | 1000 | 0 | 1000 |
| doubles: random magnitudes 1e−30 to 1e30, 16–17 digits | 1000 | 1000 | 0 | **270** |
| random 64-bit patterns, finite | 1000 | 1000 | 0 | **32** |
| integers up to ±2**53 | 1000 | 1000 | 0 | 1000 |
| extremes | 16 | 11 | **5** | 5 |

- **Reading is correctly rounded.** All 4,000 decimal strings came back bit for bit, so Python's shortest `repr` plus `BEST32.` is an exact input encoding.
- **Subnormal doubles can't be read.** The five unreadable values are exactly the subnormals: `5e-324` (twice, because `4.9e-324` is the same double), `-5e-324`, `1e-320` and `2.225073858507201e-308`. The smallest normal double and ±`1.7976931348623157e308` are read exactly.
- **`BEST32.` has a precision floor.** The worst relative error was 4.4e−10: `-1.7192679937594815e-05` printed as `-1.719267993E-5`, which is 10 significant digits.
- **Datetimes.** All 4,016 random microsecond datetimes from 1900 to 2090 came back exact through `HEX16.`. Through `E8601DT26.6` text, 4,006 did: the 10 misses are all before 1960 (1936–1949), each ±1µs out.
- **Other informats and formats** (an earlier exploration): the `32.`, `BEST32.`, `E32.` and `COMMA32.` informats all read 20 hard strings correctly rounded, `-0.0` and `1e+20` included. The `E32.` and `32.15` formats are worse than `BEST32.`: `E32.` writes π as `3.1415926535897000000000000E+00`.

### SAS calendar probe

| Date | SAS day | Days after 1960-01-01 in Python and Spark | Difference |
|---|---|---|---|
| 1600-02-29, 2000-02-29, 2400-02-29 | valid | valid | 0 |
| 4000-02-28 | 745153 | 745153 | 0 |
| **4000-02-29** | **missing (not a date)** | 745154 | |
| 4000-03-01 | 745154 | 745155 | 1 |
| **8000-02-29** | **missing** | 2206124 | |
| 8000-03-01 | 2206123 | 2206125 | 2 |
| **9999-12-31** | **2936547** | **2936549** | **2** |

SAS's calendar has no 29 February in years divisible by 4000. Labels agree, because `YYMMDD10.` prints `9999-12-31`, but **day numbers and date arithmetic differ** after 4000-02-28. This matters for the insurer's open-ended `9999-12-31` end dates. The text-vs-`HEX16.` cross-check caught it: without the check, the parser would have turned SAS's 2936547 into 9999-12-29. The engine now converts with SAS's calendar (`SAS_SKIPPED_LEAP_DAYS`), and the writer refuses 4000-02-29 and 8000-02-29. The proposed trap card SAS-16 rests on this probe (see the open points).

**Timing.** A session starts in 5.1–5.7 s and ends in 1 s; a small `submit` takes 0.4–0.6 s, an upload 4.6–6.1 s and a download 3.6–4.2 s per file whatever its size, because saspy's round trips dominate; one table in takes about 5.6 s, one table out (contents, export and 3 downloads) about 12.4 s, and the whole spike 64–67 s. If capture needs speed, zip the three output files on the server (FILENAME ZIP or ODS PACKAGE) and download one file per table.

### Gotchas, each with its evidence

1. **`BEST32.` isn't exact.** It writes at most 15 significant digits, as few as 10 for small numbers, and `0` for `-0.0` and for subnormals (the planted and bulk tables). **The fix is the `HEX16.` sidecar**, which round-tripped every double in every probe.
2. **SAS OnDemand starts sessions with `NONOTES`.** `getoption('notes')` returned `NONOTES`, so the log had no records-read lines, no observation counts, no *Invalid data* and no *Missing values were generated*. `SasSession` now sets `options source notes;` at the start. Without it, golden logs are useless and informat failures go unseen.
3. **`E8601DT26.6` calls an empty field invalid data.** With notes on, an empty or `.` datetime field gave *"NOTE: Invalid data for ts in line 2 4-4."* and `_ERROR_=1`; empty fields read with `YYMMDD10.` or `BEST32.` don't. So the read step reads datetimes as `$26.` text and runs `INPUT(text, E8601DT26.6)` only when the field is present. A malformed datetime still shows up, as *Invalid argument to function INPUT*.
4. **`ENCODING='UTF-8'` on an output file writes a BOM.** Without `nobom`, SAS wrote the bytes `EF BB BF` before the header, so the first column name came back as `﻿"varnum"`. The export now uses `nobom`, which works on 9.4M9, and the parser reads `utf-8-sig` anyway.
5. **The SAS calendar has no 29 February 4000 or 29 February 8000** (the calendar probe).
6. **Subnormal doubles can't be read** (the bulk probe). The writer refuses them with a clear message.
7. **`E8601DT26.6` text is off by ±1µs for some pre-1960 values, and overflows after 9999.** 10 of 1,278 pre-1960 values in the probe were off, and 9999-12-31T23:59:59.999999 read as `10000-01-01T00:00:00` and printed as asterisks. `HEX16.` plus exact rounding to the nearest microsecond is right in every case.
8. **Microseconds are exact only within 2**33 s of 1960 (1688–2232).** At 2**33 s the spacing between doubles reaches 1.9µs. The writer warns beyond this range.
9. **Character values.** DSD list input with `:$CHARw.` keeps leading blanks inside quotes, un-doubles `""`, keeps commas, `.`, tabs, fadas and `€`, and needs no `~` or `DEQUOTE`. Lengths are bytes in this UTF-8 session (`Seán Ó Briain` is 13 characters and 15 bytes). Line breaks inside values are impossible, because INFILE ends the record there, so the writer refuses them.
10. **`VALIDVARNAME=ANY` on OnDemand.** A job could create a name like `'Total Paid'n`, so the export refers to every non-V7 name with a name literal, which the tests cover.
11. **saspy's upload judges an overwrite by comparing file attributes**, so a re-upload within the same second could report failure. `SasSession.upload` deletes the remote file first, then checks the remote size against the local size.
12. **The SAS user ID appears in the logs**, in paths and in `Owner Name=…` lines. `SasSession` redacts the home path and the user ID at word boundaries, in every kept log and every error message.
13. **`~` works in SAS paths** on the server. The engine still resolves `%sysget(HOME)` once and uses absolute paths.

### Decisions

- **Numeric informat: `BEST32.`, for integers, decimals and doubles alike.** It's an alias of `32.`, and it never implies a decimal point: `32.2` would turn `123` into `1.23`. Every probe showed it correctly rounded, 17-digit strings, `-0.0` and `E`-notation included, so with Python's shortest `repr` the input is exact and readable. Integers beyond 2**53, infinities and subnormals are refused before upload.
- **Dates: `YYMMDD10.`. Datetimes: `E8601DT26.6`, staged through text for NULLs,** and always written with six decimals.
- **Character values: `$CHARw.`, with `w` the longest value in UTF-8 bytes** (or a declared length). Leading blanks are kept; trailing blanks can't be, because SAS pads values. On export a blank value is written as NULL: that's SAS's own meaning, and it matches the contract's `blank_is_null` and `rtrim` policies.
- **Export formats.** The plan's `BEST32.`, `YYMMDD10.`, `E8601DT26.6` and `$CHARw.` are kept, and **`HEX16.` is added** for every numeric variable, in `<stem>.hex.csv`, written by the same DATA step with each row numbered by `_lansh_obs`. The parser takes values from `HEX16.` after checking that the text agrees, within a relative 1e−7 and with the same missing values. `text_differs` counts, per column, where text alone would have been wrong: keep it in the golden manifest.
- **Typing comes from PROC CONTENTS plus `FMTINFO(format,'cat')`.** `FMTINFO` gives `date` for YYMMDD, DATE, MMDDYY, E8601DA and NLDATE; `datetime` for DATETIME, E8601DT and DTDATE; and `time` for TIME, which is kept as float seconds. Anything else, including DOLLAR (`curr`), unknown and user formats, is a plain `float64` number.
- **Physical order is `_row_seq` order.** The writer sorts by it and refuses duplicates and NULLs, so NODUPKEY, RETAIN and FIRST./LAST. see the same order in SAS as in Spark.

### Decided fallback: the paste route (plan §7.3)

**Trigger:** saspy can't connect, or SAS OnDemand's IOM service is unavailable, when golden outputs must be captured. The route reuses the engine's code, so the bytes and the parsing are identical. It needs two pastes, because the export must know each output's PROC CONTENTS metadata:

1. `write_input_csv` writes the inputs. Upload them once through SAS Studio to `~/lansh/inputs/`: same files, same bytes.
2. Paste program A (generated as `estate/sas/run_all.sas`): `options source notes;`, then `proc printto log='~/lansh/golden/run_all.log' new;`, a `read_step` for each input, the SAS jobs in dependency order writing their outputs to a permanent library (`libname golden '~/lansh/golden';`), and for each output a `contents_step` plus an `export_step` of the metadata.
3. Download the metadata CSVs. Python then generates program B: an `export_step`, with `HEX16.`, for each output.
4. Paste program B. It zips the CSVs, the sidecars, the metadata and the log into `~/lansh/golden.zip` (ODS PACKAGE).
5. Download the zip into `estate/golden/_sas_drop/` (gitignored). `parse_export` reads it exactly as on the saspy route.

Not built yet, deliberately, because saspy works: the two program generators and a `lansh estate golden --paste` option. Both are small, since every SAS step they need already exists and is tested. If the two pastes prove awkward, a single pass is possible with a SAS-side generator (CALL EXECUTE over `work._lansh_meta`), but it would need its own live test.

### Open points

- **Proposed trap card SAS-16** (a team decision, asked at G1): SAS dates have no 29 February in years divisible by 4000. Day counts across 4000-02-28 differ from Spark's by one day per such year, so 2 days for `'31DEC9999'd`. Shape: date arithmetic with the `9999-12-31` sentinel, such as `end_dt - start_dt`. Fix guidance: compare labels, not day numbers, or adjust explicitly. Not planted in any job yet.
- **`text_differs` isn't in the golden manifest yet.** `GoldenManifest` has no field for it, so adding one is a contract change. The spike's other requests are done: §7.3 is corrected, a SAS output's extra raw files are kept as `GoldenOutput.sidecars`, and the progress log records the spike.
