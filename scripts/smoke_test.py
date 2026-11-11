"""
Environment smoke test: each check prints OK, SKIP or FAIL with the reason.

Run with ``make smoke``. Checks: Spark + Delta on Java 21, sqlglot, SQL Server, the Claude
Code CLI on the subscription (no API key), and SAS OnDemand through saspy. README.md setup
step 6 lists what each line should say.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from lansh.config import env
from lansh.llm.backend import child_env


def spark_delta() -> str:
    """
    Start Spark with Delta and try its division and its case- and space-insensitive collation.

    Spark should give 3.5 for ``7/2``, where T-SQL truncates to 3 (trap TSQL-03). Under
    ``UTF8_LCASE_RTRIM``, ``'abc'`` should equal ``'ABC  '``, as it does in SQL Server, whose
    equality ignores case and trailing spaces (traps TSQL-01 and TSQL-02).

    Returns:
        The Spark and Java versions, with both results.
    """
    from lansh.spark import get_spark

    spark = get_spark("smoke")
    java = spark.sparkContext._jvm.java.lang.System.getProperty("java.version")
    row = spark.sql("SELECT 7/2 AS d, 'abc' COLLATE UTF8_LCASE_RTRIM = 'ABC  ' AS ci").first()
    return (
        f"Spark {spark.version} on Java {java}: 7/2 = {row.d}, "
        f"case- and space-insensitive match = {row.ci}"
    )


def sqlglot_check() -> str:
    """
    Transpile a T-SQL ``TOP`` query to Spark SQL.

    Returns:
        The Spark SQL, which should be ``SELECT * FROM claims LIMIT 5``.
    """
    import sqlglot

    return sqlglot.transpile("SELECT TOP 5 * FROM claims", read="tsql", write="spark")[0]


def sql_server() -> str:
    """
    Sign in to the legacy SQL Server as ``sa`` and read its version and collation.

    Returns:
        The server version, its collation and its answer to ``7/2``, which should be 3.

    Raises:
        RuntimeError: If ``MSSQL_SA_PASSWORD`` isn't set.
    """
    import pymssql

    password = env("MSSQL_SA_PASSWORD")
    if not password:
        raise RuntimeError("MSSQL_SA_PASSWORD is missing from .env")
    with pymssql.connect(
        server=env("LANSH_MSSQL_HOST", "localhost"),
        port=env("LANSH_MSSQL_PORT", "1433"),
        user="sa",
        password=password,
        login_timeout=10,
    ) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 7/2, CAST(SERVERPROPERTY('Collation') AS VARCHAR(100)), "
            "CAST(SERVERPROPERTY('ProductVersion') AS VARCHAR(30))"
        )
        seven_halves, collation, version = cur.fetchone()
        return f"SQL Server {version}, collation {collation}, 7/2 = {seven_halves}"


def claude_code() -> str:
    """
    Ask Claude Code one structured question on the subscription.

    It runs ``claude -p`` directly rather than through the gateway, with a one-field JSON
    schema, no tools, no user settings and no MCP servers, in an empty temporary directory.
    Like the gateway, it sends the prompt on stdin and strips the environment with
    ``child_env``.

    Returns:
        Claude's answer to ``7/2`` in T-SQL, which should be 3, and the call's API-equivalent
        cost, which isn't billed.

    Raises:
        RuntimeError: If ``claude`` can't be found, exits with an error or reports one.
    """
    exe = env("LANSH_CLAUDE_BIN") or shutil.which("claude")
    if not exe:
        raise RuntimeError("claude command not found; see README.md setup step 3")
    schema = json.dumps(
        {
            "type": "object",
            "properties": {"result": {"type": "integer"}},
            "required": ["result"],
            "additionalProperties": False,
        }
    )
    with tempfile.TemporaryDirectory() as empty_dir:
        run = subprocess.run(
            [
                exe,
                "-p",
                "--output-format",
                "json",
                "--json-schema",
                schema,
                "--tools",
                "",
                "--setting-sources",
                "",
                "--no-session-persistence",
                "--strict-mcp-config",
                "--model",
                "opus",
            ],
            input="In T-SQL, what does SELECT 7/2 return?",
            cwd=empty_dir,
            # ANTHROPIC_API_KEY would bill an API account instead of the subscription, and
            # the other stripped variables change how the call behaves
            env=child_env(),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    try:
        parsed = json.loads(run.stdout)
    except json.JSONDecodeError:
        parsed = None
    reply = parsed if isinstance(parsed, dict) else {}
    if run.returncode != 0:
        # the CLI words its error on stderr, or in the result envelope when it printed one
        said = run.stderr.strip() or str(reply.get("result") or "").strip() or run.stdout.strip()
        raise RuntimeError(f"claude exited with code {run.returncode}: {said or 'no output'}")
    if not reply:
        raise RuntimeError(f"claude printed no JSON result: {run.stdout.strip() or 'no output'}")
    if reply.get("is_error"):
        raise RuntimeError(str(reply.get("result"))[:160])
    return (
        f"7/2 = {reply['structured_output']['result']} via the subscription "
        f"(API-equivalent ${reply['total_cost_usd']:.3f}, not billed)"
    )


def sas_ondemand() -> str:
    """
    Run a one-line DATA step on SAS OnDemand through saspy and read its result from the log.

    ``intck('year', '31DEC2025'd, '01JAN2026'd)`` counts year boundaries crossed, not whole
    years, so it should print ``INTCK=1`` for dates one day apart (trap SAS-04).

    Returns:
        The ``INTCK=`` line from the SAS log, or a ``SKIP:`` message when saspy isn't set up.
    """
    if not Path("~/.config/saspy/sascfg_personal.py").expanduser().exists():
        return "SKIP: no saspy config; see README.md setup step 5"
    import saspy

    sas = saspy.SASsession(cfgname=env("LANSH_SAS_CFGNAME", "oda"))
    try:
        log = sas.submit(
            "data _null_; n = intck('year', '31DEC2025'd, '01JAN2026'd); put 'INTCK=' n; run;"
        )["LOG"]
        line = next((s.strip() for s in log.splitlines() if s.strip().startswith("INTCK=")), None)
        if line is None:
            raise RuntimeError("the SAS log has no INTCK= line")
        return line
    finally:
        sas.endsas()


CHECKS = [
    ("Spark + Delta", spark_delta),
    ("sqlglot", sqlglot_check),
    ("SQL Server", sql_server),
    ("Claude Code", claude_code),
    ("SAS OnDemand", sas_ondemand),
]


def main() -> int:
    """
    Run every check, print one line for each, then how many passed.

    Returns:
        The exit code: 1 if any check failed, otherwise 0. A SKIP counts as a pass.
    """
    failures = 0
    for name, check in CHECKS:
        try:
            result = check()
            status = "SKIP" if result.startswith("SKIP") else "OK"
            print(f"{status:5} {name}: {result}")
        except Exception as exc:  # report every failure and keep going
            failures += 1
            first_line = str(exc).splitlines()[0][:160] if str(exc) else ""
            print(f"FAIL  {name}: {type(exc).__name__}: {first_line}")
    print(f"{len(CHECKS) - failures}/{len(CHECKS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
