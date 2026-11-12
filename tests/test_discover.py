"""
Discover splits legacy code, scans it for traps and maps its lineage, checking every answer.

The T04 tests replay Claude's recorded answers (``runs/cassettes/``), so they run offline;
``test_t04_lineage_matches_the_hand_check`` is plan step 2.4's "done when".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lansh.config import REPO_ROOT
from lansh.contracts import DiffSignatureKind, Language, LineageKind, TrapKind
from lansh.discover.job import discover_job, tables_in
from lansh.discover.lineage import verify_lineage
from lansh.discover.split import blank_comments, numbered, split_code
from lansh.discover.traps import (
    load_cards,
    merge_findings,
    rule_findings,
    rule_scan,
    traps_for,
    verify_findings,
)
from lansh.estate.inventory import load_inventory
from lansh.lakehouse import input_schemas, output_columns
from lansh.llm.answers import LineageAnswer, TrapScanAnswer
from lansh.llm.gateway import ClaudeGateway

T04 = REPO_ROOT / "estate" / "tsql" / "T04_usp_build_claims_summary.sql"


def blocks_of(path: Path, language: Language) -> list:
    """
    Split one legacy file.
    """
    return split_code(path.read_text(encoding="utf-8"), language)


### Splitting


def test_comments_are_blanked_in_place() -> None:
    sql = "SELECT 1 -- MERGE here\n/* a MERGE\n   /* nested */ */ SELECT 'x -- y' AS s;"
    blanked = blank_comments(sql, Language.TSQL)
    assert len(blanked) == len(sql)
    assert blanked.count("\n") == sql.count("\n")
    assert "MERGE" not in blanked
    assert "'x -- y'" in blanked  # comment markers inside strings stay
    sas = "* a comment with merge;\ndata x; /* merge */ set y; run;"
    assert "merge" not in blank_comments(sas, Language.SAS)


def test_tsql_splits_into_statements_with_exact_lines() -> None:
    blocks = blocks_of(T04, Language.TSQL)
    by_start = {b.line_start: b for b in blocks}
    assert by_start[45].kind == "other"  # CREATE OR ALTER PROCEDURE ... AS BEGIN, peeled off
    assert (by_start[63].line_end, by_start[63].kind) == (
        74,
        "statement",
    )  # SELECT INTO #open_claims
    assert by_start[129].line_end == 159  # the final INSERT ... SELECT
    assert all(b.sqlglot_parsed for b in blocks if b.kind == "statement")
    t05 = blocks_of(REPO_ROOT / "estate/tsql/T05_usp_claim_aging.sql", Language.TSQL)
    unparsed = [b for b in t05 if b.sqlglot_parsed is False]
    assert unparsed  # the cursor declarations and fetches
    assert all(re.match(r"(DECLARE \w+ CURSOR|FETCH)", " ".join(b.code.split())) for b in unparsed)


def test_sas_splits_into_steps_procs_and_macros() -> None:
    blocks = blocks_of(REPO_ROOT / "estate/sas/S04_risk_scoring.sas", Language.SAS)
    assert [b.kind for b in blocks] == [
        "data_step",
        "proc",
        "proc",
        "macro",
        "other",
        "proc",
        "data_step",
    ]
    assert blocks[3].text.lstrip().startswith("%macro")
    assert "%mend" in blocks[3].text


def test_numbered_lines() -> None:
    assert numbered("a\nb") == "1 | a\n2 | b"


def test_tables_read_and_written() -> None:
    blocks = blocks_of(T04, Language.TSQL)
    code = "".join(b.code + "\n" for b in blocks)
    reads, writes = tables_in(code, Language.TSQL)
    assert reads == [
        "stg.claim_payments",
        "stg.claim_reserves",
        "stg.claims",
        "stg.policy_snapshots",
    ]
    assert writes == ["rpt.claims_summary"]


### The trap library and the rule pass


def test_trap_library_is_complete_and_valid() -> None:
    cards = load_cards()
    assert len(cards) == 35  # TSQL-01..19 and SAS-01..16 (SAS-16 accepted at G1)
    for card in cards.values():
        for rule in card.detection:
            if rule.kind == "regex":
                re.compile(rule.pattern or "")
    assert traps_for(Language.TSQL)[DiffSignatureKind.CASE_SPLIT] == ["TSQL-01", "TSQL-19"]
    constructs = {c.trap_id for c in cards.values() if c.kind is TrapKind.CONSTRUCT}
    assert {"TSQL-09", "TSQL-12", "TSQL-13", "SAS-13", "SAS-14"} <= constructs


def test_tsql07_division_recipe_reproduces_sql_server() -> None:
    """
    Card TSQL-07's recipe gives SQL Server's truncated quotients, measured on SQL Server 2022.

    The held-out run found the card wrong: SQL Server truncates a DECIMAL quotient toward zero
    at its result scale, where Spark rounds (Appendix F).
    """
    from pyspark.sql import functions as F

    from lansh.discover.traps import load_cards
    from lansh.spark import get_spark

    card = load_cards()["TSQL-07"]
    assert "truncates a DECIMAL quotient" in " ".join(card.fix_guidance.split())
    assert {"decimal(20,2)", "1000000"} <= set(card.allowed_literals)
    spark = get_spark()
    frame = spark.createDataFrame([("15000.99", "20000"), ("-2", "3")], ["a", "b"])
    q = F.col("a").cast("decimal(20,2)") / F.col("b").cast("decimal(20,2)")
    scaled = q * 1000000
    truncated = F.when(q >= 0, F.floor(scaled)).otherwise(F.ceil(scaled)) / 1000000
    rows = frame.select(
        truncated.cast("decimal(38,6)").alias("q"),
        truncated.cast("decimal(38,6)").cast("decimal(12,4)").alias("ratio"),
        (F.col("a").cast("decimal(38,2)") / F.col("b").cast("decimal(38,2)")).alias("spark"),
    ).collect()
    # SQL Server: 0.750049 and -0.666666 (the CAST to DECIMAL(12,4) then rounds: 0.7500)
    assert [str(r["q"]) for r in rows] == ["0.750049", "-0.666666"]
    assert str(rows[0]["ratio"]) == "0.7500"
    assert [str(r["spark"]) for r in rows] == ["0.750050", "-0.666667"]  # Spark's own rounds


def test_rule_pass_finds_candidates_and_skips_logging() -> None:
    text = T04.read_text()
    blocks = split_code(text, Language.TSQL)
    candidates = rule_scan(blocks, Language.TSQL)
    lines = text.splitlines()
    assert {c.line for c in candidates if c.trap_id == "TSQL-16"} == {143, 145}
    assert not any(lines[c.line - 1].strip().startswith("EXEC") for c in candidates)
    findings = rule_findings("T04", text, candidates)
    (temp,) = [f for f in findings if f.trap_id == "TSQL-13"]  # one span for a construct
    assert (temp.line_start, temp.detector) == (61, "rule")


def test_agent_findings_are_verified() -> None:
    inventory = load_inventory()
    job = inventory.job("T04")
    text = T04.read_text()
    answer = TrapScanAnswer.model_validate(
        {
            "findings": [
                {
                    "trap_id": "TSQL-05",
                    "line_start": 136,
                    "line_end": 136,
                    "confidence": 0.9,
                    "note": "+",
                },
                {
                    "trap_id": "SAS-01",
                    "line_start": 10,
                    "line_end": 10,
                    "confidence": 0.9,
                    "note": "x",
                },
                {
                    "trap_id": "TSQL-04",
                    "line_start": 900,
                    "line_end": 901,
                    "confidence": 0.9,
                    "note": "x",
                },
            ]
        }
    )
    accepted, refused = verify_findings(job, text, answer)
    assert [(f.trap_id, f.snippet) for f in accepted] == [
        ("TSQL-05", text.splitlines()[135].strip())
    ]
    assert len(refused) == 2
    rules = rule_findings("T04", text, rule_scan(split_code(text, Language.TSQL), Language.TSQL))
    merged = merge_findings(rules, accepted)
    assert {f.trap_id for f in merged} == {"TSQL-05", "TSQL-13"}  # constructs kept from the rules


### Lineage


def test_lineage_refuses_columns_that_do_not_exist() -> None:
    inventory = load_inventory()
    job = inventory.job("T04")
    answer = LineageAnswer.model_validate(
        {
            "edges": [
                edge("status", "stg.claims", "STATUS"),  # case doesn't matter
                edge("status", "stg.claims", "state"),  # no such column
                edge("nope", "stg.claims", "status"),  # no such output column
                edge("status", "#open_claims", "status"),  # a temp table is not an input
            ],
            "notes": "",
        }
    )
    edges, refused = verify_lineage(
        job,
        answer,
        input_schemas(inventory, job),
        {"rpt.claims_summary": output_columns(inventory, "rpt.claims_summary")},
    )
    assert [(e.output_column, e.input_column, e.verified) for e in edges] == [
        ("status", "status", True)
    ]
    assert len(refused) == 3


def edge(output: str, table: str, column: str) -> dict:
    """
    One derives edge of rpt.claims_summary, as the Lineage agent writes it.
    """
    return {
        "output_table": "rpt.claims_summary",
        "output_column": output,
        "input_kind": "column",
        "input_table": table,
        "input_column": column,
        "kind": "derives",
        "transform": "",
        "lines": [67],
        "confidence": 0.9,
    }


# T04's lineage, checked by hand against the legacy code
C, P, R, S = "stg.claims", "stg.claim_payments", "stg.claim_reserves", "stg.policy_snapshots"
RESERVES = {(R, "reserve_amount"), (R, "reserve_type")}
T04_HAND_CHECK = {
    "claim_id": {(C, "claim_id")},
    "claim_number": {(C, "claim_number")},
    "claim_ref": {(C, "lob_code"), (C, "claim_number"), (C, "handler_code")},
    "policy_id": {(C, "policy_id")},
    "policy_number": {(S, "policy_number")},
    "lob_code": {(C, "lob_code")},
    "status": {(C, "status")},
    "handler_code": {(C, "handler_code")},
    "loss_date": {(C, "loss_date")},
    "loss_date_text": {(C, "loss_date")},
    "reported_date": {(C, "reported_date")},
    "reported_period": {(C, "reported_date")},
    "days_open": {(C, "reported_date")},
    "n_payments": {(P, "payment_id")},
    "total_paid": {(P, "amount")},
    "indemnity_reserve": RESERVES,
    "expense_reserve": RESERVES,
    "current_reserve": RESERVES,
    "incurred": {(P, "amount"), *RESERVES},
    "as_of_date": set(),
}


@pytest.fixture(scope="module")
def t04_discovery():
    """
    Discover T04 from the recorded answers (replay mode, no Claude access).
    """
    inventory = load_inventory()
    return discover_job(inventory.job("T04"), inventory, ClaudeGateway(mode="replay"))


def test_t04_lineage_matches_the_hand_check(t04_discovery) -> None:
    derives: dict[str, set] = {c: set() for c in T04_HAND_CHECK}
    for e in t04_discovery.lineage:
        assert e.verified
        if e.kind is LineageKind.DERIVES and e.input_kind == "column":
            derives[e.output_column].add((e.input_table, e.input_column))
    assert derives == T04_HAND_CHECK
    filters = {
        (e.input_table, e.input_column)
        for e in t04_discovery.lineage
        if e.kind is LineageKind.FILTERS
    }
    assert {(C, "status"), (C, "reported_date")} <= filters
    # sqlglot, composing its per-statement lineage through the temp tables, agrees on all 20
    assert t04_discovery.stats["sqlglot_traced_columns"] == 20
    assert t04_discovery.stats["sqlglot_agreeing_columns"] == 20
    assert t04_discovery.blockers == []
    assert t04_discovery.discovery.status == "parsed"


def test_t04_trap_scan_finds_the_engine_differences(t04_discovery) -> None:
    found = {(f.trap_id, f.line_start) for f in t04_discovery.traps}
    # the open-status filter, the NULL concatenation and both CONVERT styles
    assert {
        ("TSQL-01", 73),
        ("TSQL-02", 73),
        ("TSQL-05", 136),
        ("TSQL-16", 143),
        ("TSQL-16", 145),
    } <= found
    assert all(f.snippet for f in t04_discovery.traps)
