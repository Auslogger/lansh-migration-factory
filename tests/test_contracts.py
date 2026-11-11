"""
The shared contracts round-trip through JSON, and their validators refuse bad data.

``examples()`` builds one realistic instance of every model in ``CONTRACT_MODELS``, and the
first four tests cover them all. The last two check the YAML reader and writer behind
``estate/jobs.yaml``.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from lansh import contracts as c
from lansh.estate.inventory import dump_inventory, parse_yaml

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
SHA = "a" * 64
SHA2 = "b" * 64


def _col(name: str, data_type: str = "string", **kw) -> c.ColumnSpec:
    """
    Build a column spec, of type string unless another type is given.
    """
    return c.ColumnSpec(name=name, data_type=data_type, **kw)


def _ref(table: str, column: str) -> c.ColumnRef:
    """
    Build a reference to one column of one table.
    """
    return c.ColumnRef(table=table, column=column)


def _job(job_id: str, inputs: list[str], outputs: list[str], **kw) -> c.JobSpec:
    """
    Build a job that reads ``inputs`` and writes ``outputs``, with T-SQL defaults for the rest.

    ``kw`` can override the language, entrypoint and invocations, or set any other field.
    """
    return c.JobSpec(
        job_id=job_id,
        name=f"usp_{job_id.lower()}",
        language=kw.pop("language", c.Language.TSQL),
        path=f"estate/tsql/{job_id}.sql",
        entrypoint=kw.pop("entrypoint", f"dw.usp_{job_id.lower()}"),
        invocations=kw.pop("invocations", [c.JobInvocation(params={"AsOfDate": "2025-12-31"})]),
        inputs=inputs,
        outputs=[c.JobOutput(table=t) for t in outputs],
        **kw,
    )


def _recon(**kw) -> c.ReconReport:
    """
    Build a matching T04 reconciliation report, with any field replaced from ``kw``.
    """
    base = dict(
        job_id="T04",
        table="rpt.claims_summary",
        mode=c.ReconMode.ISOLATED,
        status=c.ReconStatus.MATCH,
        counts=c.CountCheck(legacy=10, candidate=10),
        started_at=T0,
        duration_seconds=1.0,
    )
    base.update(kw)
    return c.ReconReport(**base)


def examples() -> dict[type[c.Model], c.Model]:
    """
    Build one realistic instance of every contract model, keyed by its type.
    """
    ref = _ref("stg.customers", "date_of_birth")
    column = _col(
        "email",
        legacy_type="VARCHAR(100)",
        max_length=100,
        tags=[c.ColumnTag.PII],
        description="Contact email; trailing spaces are kept   ",
    )
    schema = c.TableSchema(
        name="stg.customers",
        layer=c.Layer.BRONZE,
        columns=[_col("customer_id", "int", nullable=False), column, _col("_row_seq", "int")],
        primary_key=["customer_id"],
        row_order_column="_row_seq",
    )
    invocation = c.JobInvocation(label="batch 1", params={"SnapshotDate": "2025-06-30"})
    output = c.JobOutput(table="dw.dim_policy", volatile_columns=["load_ts"])
    t01 = _job("T01", ["stg.customers"], ["dw.dim_customer"])
    t02 = c.JobSpec(
        job_id="T02",
        name="usp_load_dim_policy",
        language=c.Language.TSQL,
        path="estate/tsql/T02_usp_load_dim_policy.sql",
        entrypoint="dw.usp_load_dim_policy",
        invocations=[invocation, c.JobInvocation(params={"SnapshotDate": "2025-12-31"})],
        inputs=["stg.policy_snapshots", "dw.dim_customer"],
        outputs=[output],
        state_tables=["dw.dim_policy"],
    )
    inventory = c.EstateInventory(
        as_of_date=date(2025, 12, 31),
        legacy_database="SynthInsureDW",
        sources=["stg.customers", "stg.policy_snapshots"],
        audit_tables=["etl.etl_log"],
        jobs=[t01, t02],
    )
    block = c.CodeBlock(
        job_id="T04", index=0, kind="statement", line_start=40, line_end=58, sqlglot_parsed=False
    )
    discovery = c.JobDiscovery(
        job_id="T04",
        status="flagged",
        flags=["MERGE not parsed"],
        blocks=[block],
        reads=["stg.claims"],
        writes=["rpt.claims_summary"],
    )
    edge = c.LineageEdge(
        job_id="T04",
        output_table="rpt.claims_summary",
        output_column="total_paid",
        input_table="stg.claim_payments",
        input_column="amount",
        kind=c.LineageKind.DERIVES,
        transform="SUM over payments up to the as-of date",
        source="llm",
        confidence=0.9,
        verified=True,
        evidence_lines=[42, 43],
    )
    flow = c.TaggedFlow(
        flow_id="F-1",
        tag=c.ColumnTag.PROTECTED,
        source=ref,
        output=_ref("rpt.risk_scores", "risk_score"),
        path=[ref, _ref("dw.dim_customer", "date_of_birth"), _ref("rpt.risk_scores", "risk_score")],
        job_ids=["T01", "S04"],
    )
    wave = c.Wave(number=1, job_ids=["T01", "T04"])
    job_edge = c.JobEdge(upstream="T01", downstream="T02", tables=["dw.dim_customer"])
    plan = c.EstatePlan(waves=[wave, c.Wave(number=2, job_ids=["T02"])], edges=[job_edge])
    rule = c.DetectionRule(kind="regex", pattern=r"\bDATEDIFF\s*\(", description="DATEDIFF call")
    card = c.TrapCard(
        trap_id="TSQL-01",
        title="Case-insensitive collation",
        language=c.Language.TSQL,
        kind=c.TrapKind.SEMANTIC,
        legacy_behaviour="'Open' = 'OPEN' is true",
        spark_behaviour="false",
        fix_guidance="compare under UTF8_LCASE_RTRIM",
        detection=[rule],
        diff_signatures=[c.DiffSignatureKind.CASE_SPLIT],
        allowed_literals=["UTF8_LCASE_RTRIM"],
    )
    finding = c.TrapFinding(
        job_id="T04",
        trap_id="TSQL-01",
        line_start=40,
        line_end=41,
        snippet="WHERE c.status IN ('OPEN','REOPENED')",
        detector="rule",
        confidence=0.9,
    )
    policy = c.ComparisonPolicy(
        kind=c.PolicyKind.CI_RTRIM, reason="SQL Server GROUP BY returns any case variant"
    )
    contract_col = c.ContractColumn(name="status", data_type="string", policy=policy)
    sla = c.SlaSpec(max_runtime_seconds=120, expected_rows=4200, row_tolerance_pct=5)
    contract = c.DataContract(
        job_id="T04",
        table="gold.claims_summary",
        legacy_table="rpt.claims_summary",
        layer=c.Layer.GOLD,
        grain="one row per open claim",
        keys=["claim_id"],
        columns=[c.ContractColumn(name="claim_id", data_type="int"), contract_col],
        sla=sla,
    )
    impact = c.DefectImpact(
        rows_affected=812,
        amount_affected="1234567.89",
        amount_column="total_paid",
        measured_on="golden:T04",
        query="SELECT COUNT(*) FROM ...",
    )
    defect = c.SuspectedDefect(
        defect_id="T04-D1",
        job_id="T04",
        title="Payments counted once per reserve row",
        description="payments and reserves are joined before aggregation",
        intended_behaviour="aggregate each separately",
        evidence_lines=[55],
        impact_query="SELECT ...",
        impact=impact,
        source="llm",
        confidence=0.8,
    )
    decision = c.DefectDecision(
        defect_id="T04-D1",
        job_id="T04",
        decision=c.DefectDecisionKind.REPRODUCE,
        reason="reproduce through cut-over; finance to fix after",
        decided_by="reviewer",
        decided_at=T0,
        gate=c.Gate.H2,
    )
    flow_decision = c.FlowDecision(
        flow_id="F-1",
        decision="reproduce_flagged",
        reason="age drives the score; refer to pricing committee",
        decided_by="reviewer",
        decided_at=T0,
    )
    literal = c.LiteralFinding(value="yyyyMMdd", line=31, provenance="trap_card")
    artifact = c.MigrationArtifact(
        job_id="T04",
        module_path="migrated/jobs/t04.py",
        code_sha256=SHA,
        legacy_path="estate/tsql/T04_usp_build_claims_summary.sql",
        legacy_sha256=SHA2,
        translator="claude",
        model="claude-opus-5-5",
        traps_handled=["TSQL-01", "TSQL-05"],
        defects_reproduced=["T04-D1"],
        literals=[literal],
        created_at=T0,
    )
    rows = c.TableRows(
        table="stg.claims", columns=["claim_id", "handler_code"], rows=[["1", None], ["2", "H101"]]
    )
    test_case = c.TestCase(
        test_id="T04-TSQL-05-1",
        job_id="T04",
        trap_id="TSQL-05",
        description="NULL handler code makes the claim reference NULL",
        inputs=[rows],
        expected=[
            c.TableRows(
                table="rpt.claims_summary", columns=["claim_id", "claim_ref"], rows=[["1", None]]
            )
        ],
        expected_source="legacy_engine",
    )
    mismatch = c.TypeMismatch(column="days_open", legacy_type="int", candidate_type="bigint")
    schema_diff = c.SchemaDiff(type_mismatches=[mismatch])
    part = c.PartitionCount(partition="lob_code=MOT", legacy=10, candidate=9)
    counts = c.CountCheck(legacy=100, candidate=99, by_partition=[part])
    total = c.TotalCheck(
        column="total_paid", legacy="48211904.17", candidate="47005310.62", matches=False
    )
    keys = c.KeyIntegrity(candidate_duplicate_keys=1)
    row_counts = c.RowCounts(matched=95, value_diff=3, missing=2, extra=1)
    col_diff = c.ColumnDiff(
        column="status",
        policy=c.PolicyKind.EXACT,
        n_rows=3,
        samples=[{"claim_id": 7, "legacy": "Open", "candidate": "OPEN"}],
    )
    signature = c.DiffSignature(
        kind=c.DiffSignatureKind.CASE_SPLIT,
        column="status",
        n_rows=2,
        explanation="every missing row has a mixed-case status",
        suspected_traps=["TSQL-01"],
    )
    report = c.ReconReport(
        job_id="T04",
        table="rpt.claims_summary",
        mode=c.ReconMode.ISOLATED,
        status=c.ReconStatus.MISMATCH,
        run_id="run-1",
        code_sha256=SHA,
        keys=["claim_id"],
        schema_diff=schema_diff,
        counts=counts,
        totals=[total],
        key_integrity=keys,
        rows=row_counts,
        column_diffs=[col_diff],
        signatures=[signature],
        explanation="2 claims missing: mixed-case status (TSQL-01)",
        golden_sha256=SHA,
        started_at=T0,
        duration_seconds=3.5,
    )
    heal = c.HealAttempt(
        job_id="T04",
        attempt=1,
        diagnosis="case-sensitive status filter",
        suspected_traps=["TSQL-01"],
        patch_summary="compare status under UTF8_LCASE_RTRIM",
        code_sha256_before=SHA,
        code_sha256_after=SHA2,
        score_before=(0, 1, 1, 6),
        score_after=(0, 0, 0, 0),
        report_before="runs/r1/T04.json",
        report_after="runs/r1/T04-heal1.json",
        guardrails_passed=True,
        kept=True,
        recon_status_after=c.ReconStatus.MATCH,
        started_at=T0,
        duration_seconds=40.0,
    )
    escalation = c.Escalation(
        escalation_id="E-1",
        job_id="T05",
        stage=c.Stage.RECONCILE,
        reason="heal_exhausted",
        diagnosis="cursor NULL propagation",
        attempts=3,
        created_at=T0,
    )
    evidence = c.EvidenceRef(kind="contract", ref="migrated/contracts/T04.json", sha256=SHA)
    gate = c.GateDecision(
        decision_id="g-0001",
        gate=c.Gate.H2,
        stage=c.Stage.DESIGN,
        job_ids=["T04"],
        outcome=c.GateOutcome.APPROVE,
        reviewer="reviewer",
        reason="ci_rtrim justified by collation",
        evidence=[evidence],
        warnings=["non-exact policy on status"],
        shown_at=T0,
        decided_at=T0 + timedelta(seconds=95),
    )
    schedule = c.WaveSchedule(
        wave=2, job_ids=["T02", "T08"], depends_on_waves=[1], trigger="after wave 1"
    )
    sla_check = c.SlaCheck(
        job_id="T04",
        table="rpt.claims_summary",
        runtime_seconds=12.5,
        rows=2238,
        max_runtime_seconds=10,
        expected_rows=2200,
        row_tolerance_pct=5,
        breaches=["runtime"],
    )
    usage = c.LLMUsage(
        call_id="call-1",
        run_id="run-1",
        agent="translator",
        job_id="T04",
        stage=c.Stage.GENERATE,
        model_requested="opus",
        models_used=["claude-opus-5-5"],
        effort=c.Effort.HIGH,
        cli_version="2.1.311",
        request_sha256=SHA,
        num_turns=2,
        input_tokens=1200,
        output_tokens=800,
        duration_ms=15000,
        cost_usd_equivalent=0.12,
    )
    metrics = c.RunMetrics(
        run_id="run-1",
        job_id="T04",
        wave=1,
        stage=c.Stage.RECONCILE,
        started_at=T0,
        llm_calls=3,
        heal_attempts=1,
        status=c.RunStatus.MATCH,
        sla=[sla_check],
    )
    artifact_ref = c.ArtifactRef(path="runs/showcase/scorecard.json", sha256=SHA)
    metric = c.Metric(name="jobs_matched", value="10", unit="jobs", sources=[artifact_ref])
    fingerprint = c.TableFingerprint(
        table="stg.claims",
        path="estate/data/claims.parquet",
        rows=12000,
        file_sha256=SHA,
        content_sha256=SHA2,
    )
    golden_out = c.GoldenOutput(
        table="dw.dim_policy",
        rows=26000,
        columns=[_col("policy_sk", "int"), _col("load_ts", "timestamp_ntz")],
        raw_path="estate/golden/T02/dw.dim_policy.csv",
        raw_sha256=SHA,
        parquet_path="estate/golden/T02/dw.dim_policy.parquet",
        parquet_sha256=SHA2,
        content_sha256=SHA,
        volatile_columns=["load_ts"],
        sidecars=[c.ArtifactRef(path="estate/golden/T02/dw.dim_policy.hex.csv", sha256=SHA2)],
    )
    manifest = c.GoldenManifest(
        job_id="T02",
        engine="mssql",
        engine_version="16.0.4305.5",
        legacy_path="estate/tsql/T02_usp_load_dim_policy.sql",
        legacy_sha256=SHA,
        invocations=[invocation],
        inputs=[fingerprint],
        outputs=[golden_out],
        log_excerpt="(26000 rows affected)",
        captured_at=T0,
        capture_seconds=12.5,
        lansh_version="0.1.0",
    )
    evidence_report = c.EvidenceReport(
        job_id="T04",
        generated_at=T0,
        legacy_path="estate/tsql/T04.sql",
        legacy_sha256=SHA,
        discovery=discovery,
        code=artifact,
        lineage=[edge],
        traps=[finding],
        contracts=[contract],
        defects=[defect],
        defect_decisions=[decision],
        flows=[flow],
        flow_decisions=[flow_decision],
        recon=[report],
        heal=[heal],
        tests=[test_case],
        escalations=[escalation],
        llm_usage=[usage],
        gates=[gate],
    )
    instances: list[c.Model] = [
        ref,
        column,
        schema,
        invocation,
        output,
        t02,
        inventory,
        block,
        discovery,
        edge,
        flow,
        wave,
        job_edge,
        plan,
        rule,
        card,
        finding,
        policy,
        contract_col,
        sla,
        contract,
        impact,
        defect,
        decision,
        flow_decision,
        literal,
        artifact,
        rows,
        test_case,
        mismatch,
        schema_diff,
        part,
        counts,
        total,
        keys,
        row_counts,
        col_diff,
        signature,
        report,
        heal,
        escalation,
        evidence,
        gate,
        schedule,
        sla_check,
        usage,
        metrics,
        artifact_ref,
        metric,
        fingerprint,
        golden_out,
        manifest,
        evidence_report,
    ]
    return {type(m): m for m in instances}


def test_every_contract_model_has_an_example() -> None:
    assert set(examples()) == set(c.CONTRACT_MODELS)


@pytest.mark.parametrize("model_type", c.CONTRACT_MODELS, ids=lambda t: t.__name__)
def test_round_trips_through_json(model_type: type[c.Model]) -> None:
    """
    Each model comes back equal from JSON text and from parsed JSON, and dumps the same text.
    """
    original = examples()[model_type]
    text = original.model_dump_json()
    restored = model_type.model_validate_json(text)
    assert restored == original
    assert restored.model_dump_json() == text
    assert model_type.model_validate(json.loads(text)) == original


@pytest.mark.parametrize("model_type", c.CONTRACT_MODELS, ids=lambda t: t.__name__)
def test_json_schema_exports(model_type: type[c.Model]) -> None:
    """
    Each schema is an object that refuses unknown fields, with ASCII-only patterns like [0-9].
    """
    schema = model_type.model_json_schema()
    assert schema["type"] == "object"
    assert schema.get("additionalProperties") is False
    assert "\\d" not in json.dumps(schema)
    assert "\\w" not in json.dumps(schema)


@pytest.mark.parametrize("model_type", c.CONTRACT_MODELS, ids=lambda t: t.__name__)
def test_assignments_are_validated(model_type: type[c.Model]) -> None:
    """
    Each model takes its own values back, and a value of the wrong type changes nothing.
    """
    record = examples()[model_type]
    for name in model_type.model_fields:
        setattr(record, name, getattr(record, name))
    assert record == examples()[model_type]
    before, fields_set = record.model_copy(deep=True), set(record.model_fields_set)
    with pytest.raises(ValidationError):
        setattr(record, next(iter(model_type.model_fields)), object())
    assert record == before
    assert record.model_fields_set == fields_set


def test_assignment_a_model_validator_refuses_changes_nothing() -> None:
    """
    The record keeps its old value, and a field that was never set stays unset.
    """
    block = examples()[c.CodeBlock]
    before = block.model_copy()
    with pytest.raises(ValidationError, match="line_end is before line_start"):
        block.line_end = block.line_start - 1
    assert block == before
    assert block.line_end == 58
    literal = c.LiteralFinding(value="42", line=3, provenance="none")
    with pytest.raises(ValidationError, match="needs a reason"):
        literal.accepted_by = "reviewer"
    assert literal.accepted_by is None
    assert literal.model_fields_set == {"value", "line", "provenance"}
    # assignments the validators accept still work, and count as set
    literal.reason = "ageing threshold from the business"
    literal.accepted_by = "reviewer"
    assert not literal.blocks_h3
    assert {"reason", "accepted_by"} <= literal.model_fields_set


### Identifiers and types


def test_trailing_spaces_are_preserved() -> None:
    col = c.ColumnSpec(name="county", data_type="string", description="Dublin  ")
    assert c.ColumnSpec.model_validate_json(col.model_dump_json()).description == "Dublin  "


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        c.ColumnSpec(name="x", data_type="int", colour="red")


def test_table_names_are_canonical_lower_case() -> None:
    """
    Table names lose their brackets and case, and non-ASCII names are refused.
    """
    assert c.ColumnRef(table="[RPT].[Claims_Summary]", column="x").table == "rpt.claims_summary"
    assert c.ColumnRef(table="WORK.CLAIMS_ENRICHED", column="x").table == "work.claims_enriched"
    with pytest.raises(ValidationError):
        c.ColumnRef(table="stg.cliént", column="x")


def test_ids_are_ascii_only() -> None:
    # the job id is T04 in Arabic-Indic digits, which a \d pattern would accept
    with pytest.raises(ValidationError):
        c.CodeBlock(job_id="T٠٤", index=0, kind="statement", line_start=1, line_end=1)


def test_column_names_compare_case_insensitively() -> None:
    with pytest.raises(ValidationError, match="duplicate column names"):
        c.TableSchema(name="stg.x", columns=[_col("claim_id"), _col("CLAIM_ID")])
    schema = c.TableSchema(name="stg.x", columns=[_col("claim_id")], primary_key=["CLAIM_ID"])
    assert schema.column("Claim_Id").name == "claim_id"


@pytest.mark.parametrize(
    "bad", ["varchar(10)", "decimal(5,7)", "decimal(39,2)", "decimal(0,0)", "text"]
)
def test_unknown_or_impossible_logical_types_are_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        c.ColumnSpec(name="x", data_type=bad)


### Policies and contracts


def test_non_exact_policy_needs_a_reason_and_approval_is_not_a_field() -> None:
    with pytest.raises(ValidationError, match="needs a reason"):
        c.ComparisonPolicy(kind=c.PolicyKind.RTRIM)
    # approval is an H2 gate decision on the contract's hash, so a changed policy needs it again
    with pytest.raises(ValidationError):
        c.ComparisonPolicy(kind=c.PolicyKind.RTRIM, reason="SAS", approved_by="claude")
    assert c.ComparisonPolicy().needs_approval is False


@pytest.mark.parametrize(("rel", "abs_"), [(None, None), (1e-6, None), (1e-9, 1e-6)])
def test_float_tolerances_are_capped(rel: float | None, abs_: float | None) -> None:
    """
    A float_rel policy needs a relative tolerance, and neither tolerance may exceed 1e-9.
    """
    with pytest.raises(ValidationError):
        c.ComparisonPolicy(
            kind=c.PolicyKind.FLOAT_REL, reason="SAS double", rel_tolerance=rel, abs_tolerance=abs_
        )
    ok = c.ComparisonPolicy(
        kind=c.PolicyKind.FLOAT_REL, reason="SAS double", rel_tolerance=1e-9, abs_tolerance=1e-12
    )
    assert ok.abs_tolerance == 1e-12


def test_tolerances_and_references_belong_to_their_policies() -> None:
    with pytest.raises(ValidationError, match="only apply to float_rel"):
        c.ComparisonPolicy(kind=c.PolicyKind.RTRIM, reason="x", abs_tolerance=1e-12)
    with pytest.raises(ValidationError, match="references"):
        c.ComparisonPolicy(kind=c.PolicyKind.SURROGATE_REF, reason="FK to dim_policy")
    fk = c.ComparisonPolicy(
        kind=c.PolicyKind.SURROGATE_REF,
        reason="FK to dim_policy",
        references=_ref("dw.dim_policy", "policy_sk"),
    )
    assert fk.references.column == "policy_sk"


def _contract(columns: list[c.ContractColumn], keys: list[str]) -> c.DataContract:
    """
    Build a T02 silver contract with the given columns and business key.
    """
    return c.DataContract(
        job_id="T02",
        table="silver.dim_policy",
        legacy_table="dw.dim_policy",
        layer=c.Layer.SILVER,
        grain="one row per policy version",
        keys=keys,
        columns=columns,
    )


def test_contract_policies_fit_their_column_types() -> None:
    rel = c.ComparisonPolicy(kind=c.PolicyKind.FLOAT_REL, reason="d", rel_tolerance=1e-9)
    with pytest.raises(ValidationError, match="float_rel is for doubles"):
        _contract([c.ContractColumn(name="amt", data_type="decimal(18,2)", policy=rel)], [])
    ci = c.ComparisonPolicy(kind=c.PolicyKind.CI_RTRIM, reason="collation")
    with pytest.raises(ValidationError, match="is for text"):
        _contract([c.ContractColumn(name="n", data_type="int", policy=ci)], [])


def test_keys_cannot_be_surrogate_and_surrogates_need_a_key() -> None:
    surrogate = c.ComparisonPolicy(kind=c.PolicyKind.SURROGATE, reason="IDENTITY")
    # upper-case POLICY_SK still names the column, as names compare case-insensitively
    with pytest.raises(ValidationError, match="key column"):
        _contract(
            [c.ContractColumn(name="policy_sk", data_type="int", policy=surrogate)], ["POLICY_SK"]
        )
    with pytest.raises(ValidationError, match="needs a business key"):
        _contract([c.ContractColumn(name="policy_sk", data_type="int", policy=surrogate)], [])


### Inventory


def test_inventory_refuses_unknown_inputs_and_double_writers() -> None:
    inventory = examples()[c.EstateInventory].model_dump()
    inventory["jobs"][1]["inputs"].append("stg.nowhere")
    with pytest.raises(ValidationError, match="unknown tables"):
        c.EstateInventory.model_validate(inventory)
    inventory = examples()[c.EstateInventory].model_dump()
    # have T02 write T01's table too; the next two lines keep T02 itself valid
    inventory["jobs"][1]["outputs"][0]["table"] = "dw.dim_customer"
    inventory["jobs"][1]["state_tables"] = ["dw.dim_customer"]
    inventory["jobs"][1]["inputs"].remove("dw.dim_customer")
    with pytest.raises(ValidationError, match="more than one"):
        c.EstateInventory.model_validate(inventory)


def test_inventory_refuses_cycles() -> None:
    with pytest.raises(ValidationError, match="cycle"):
        c.EstateInventory(
            as_of_date=date(2025, 12, 31),
            legacy_database="db",
            sources=["stg.a"],
            jobs=[_job("T01", ["stg.a", "dw.b"], ["dw.a"]), _job("T02", ["dw.a"], ["dw.b"])],
        )


def test_state_tables_are_outputs_and_not_upstream_edges() -> None:
    inventory = examples()[c.EstateInventory]
    assert inventory.upstream("T02") == ["T01"]
    assert inventory.upstream("T01") == []
    with pytest.raises(ValidationError, match="must be outputs"):
        _job("T09", ["stg.a"], ["dw.x"], state_tables=["dw.y"])
    with pytest.raises(ValidationError, match="are not inputs"):
        _job("T09", ["stg.a", "dw.x"], ["dw.x"], state_tables=["dw.x"])


def test_audit_tables_may_be_written_by_every_job() -> None:
    inv = c.EstateInventory(
        as_of_date=date(2025, 12, 31),
        legacy_database="db",
        sources=["stg.a"],
        audit_tables=["etl.etl_log"],
        jobs=[
            _job("T01", ["stg.a"], ["dw.a", "etl.etl_log"]),
            _job("T02", ["stg.a"], ["dw.b", "etl.etl_log"]),
        ],
    )
    assert inv.producers() == {"dw.a": "T01", "dw.b": "T02"}


def test_inventory_merge_adds_unsealed_jobs() -> None:
    base = examples()[c.EstateInventory]
    extra = c.EstateInventory(
        as_of_date=date(2025, 12, 31),
        legacy_database="SynthInsureDW",
        sources=["stg.customers"],
        jobs=[_job("X1", ["stg.customers"], ["rpt.x1"], holdout=True, origin="isolated_agent")],
    )
    merged = base.merge(extra)
    assert [j.job_id for j in merged.jobs] == ["T01", "T02", "X1"]


def test_sas_names_respect_sas_limits() -> None:
    # the libref "warehouse" has 9 characters, and SAS allows 8
    with pytest.raises(ValidationError, match="SAS name limits"):
        _job("S09", ["warehouse.claims"], ["rpt.x"], language=c.Language.SAS, entrypoint=None)


def test_tsql_jobs_need_an_entrypoint() -> None:
    data = examples()[c.JobSpec].model_dump()
    data["entrypoint"] = None
    with pytest.raises(ValidationError, match="entrypoint"):
        c.JobSpec.model_validate(data)


def test_table_schema_checks_its_key() -> None:
    """
    A primary key may only name columns the table has.
    """
    with pytest.raises(ValidationError, match="primary key"):
        c.TableSchema(name="stg.x", columns=[_col("a")], primary_key=["b"])


### Discover


def _edge(**kw) -> c.LineageEdge:
    """
    Build a T04 lineage edge that derives ``as_of_date``, with any field replaced from ``kw``.
    """
    base = dict(
        job_id="T04",
        output_table="rpt.claims_summary",
        output_column="as_of_date",
        kind=c.LineageKind.DERIVES,
        source="llm",
    )
    base.update(kw)
    return c.LineageEdge(**base)


def test_lineage_inputs_can_be_parameters_or_constants() -> None:
    """
    Parameter and constant inputs have no table, and each kind of input names what it needs.
    """
    assert _edge(input_kind="parameter", input_column="@AsOfDate").input_table is None
    constant = _edge(input_kind="constant", output_column="claim_status", transform="'OPEN'")
    assert (constant.input_table, constant.input_column) == (None, None)
    # a filter on a constant affects whole rows, so it needs no output column
    whole_rows = _edge(kind=c.LineageKind.FILTERS, output_column=None, input_kind="constant")
    assert whole_rows.output_column is None
    with pytest.raises(ValidationError, match="needs input_table"):
        _edge(output_table="rpt.x", output_column="y")
    with pytest.raises(ValidationError, match="a constant edge has no input table"):
        _edge(input_kind="constant", input_table="stg.claims")
    with pytest.raises(ValidationError, match="names the parameter"):
        _edge(input_kind="parameter")
    with pytest.raises(ValidationError, match="needs an output column"):
        _edge(output_column=None, input_kind="parameter", input_column="@AsOfDate")


def test_tagged_flow_path_runs_from_source_to_output() -> None:
    flow = examples()[c.TaggedFlow].model_dump()
    flow["path"] = flow["path"][::-1]
    with pytest.raises(ValidationError, match="start at the source"):
        c.TaggedFlow.model_validate(flow)


def test_tagged_flow_matches_column_names_case_insensitively() -> None:
    # stg.customers.Email and stg.customers.email are one column, as everywhere else
    flow = c.TaggedFlow(
        flow_id="F-2",
        tag=c.ColumnTag.PII,
        source=_ref("stg.customers", "Email"),
        output=_ref("rpt.contacts", "EMAIL"),
        path=[_ref("stg.customers", "email"), _ref("rpt.contacts", "email")],
        job_ids=["T01"],
    )
    assert flow.source.column == "Email"  # each reference keeps its spelling


def test_estate_plan_waves_are_numbered_and_disjoint() -> None:
    with pytest.raises(ValidationError, match="numbered"):
        c.EstatePlan(waves=[c.Wave(number=2, job_ids=["T01"])])
    with pytest.raises(ValidationError, match="duplicate jobs"):
        c.EstatePlan(waves=[c.Wave(number=1, job_ids=["T01"]), c.Wave(number=2, job_ids=["T01"])])


### Reconcile and heal


def test_match_status_must_agree_with_the_numbers() -> None:
    data = examples()[c.ReconReport].model_dump()
    data["status"] = "MATCH"
    with pytest.raises(ValidationError, match="contradicts"):
        c.ReconReport.model_validate(data)
    with pytest.raises(ValidationError, match="column differences"):
        _recon(column_diffs=[c.ColumnDiff(column="x", policy=c.PolicyKind.EXACT, n_rows=2)])


def test_mismatch_needs_a_difference_and_counts_are_needed_unless_error() -> None:
    with pytest.raises(ValidationError, match="nothing differs"):
        _recon(status=c.ReconStatus.MISMATCH)
    with pytest.raises(ValidationError, match="counts are required"):
        _recon(counts=None)
    crashed = _recon(status=c.ReconStatus.ERROR, counts=None, error="AnalysisException")
    assert crashed.score == (1, 0, 0, 0)


def test_scores_order_states_by_distance_from_match() -> None:
    crashed = _recon(status=c.ReconStatus.ERROR, counts=None, error="boom")
    forty = _recon(status=c.ReconStatus.MISMATCH, rows=c.RowCounts(value_diff=40))
    missing_col = _recon(
        status=c.ReconStatus.MISMATCH, schema_diff=c.SchemaDiff(missing_columns=["x"])
    )
    match = _recon()
    assert crashed.score > missing_col.score > forty.score > match.score
    assert c.total_score([forty, match]) == (0, 0, 0, 40)


def test_a_job_without_reports_has_no_score() -> None:
    # adding up nothing would give (0, 0, 0, 0), a clean MATCH for a job never reconciled
    with pytest.raises(ValueError, match="no reports"):
        c.total_score([])


def test_heal_patch_is_kept_only_if_the_score_improves() -> None:
    data = examples()[c.HealAttempt].model_dump()
    data["score_after"] = data["score_before"]
    with pytest.raises(ValidationError, match="strictly improves"):
        c.HealAttempt.model_validate(data)
    # from a crash to 40 row differences: a crash scores worse than any number of them
    data["score_before"], data["score_after"] = (1, 0, 0, 0), (0, 0, 0, 40)
    assert c.HealAttempt.model_validate(data).kept


### Governance and the rest


def _gate(**kw) -> c.GateDecision:
    """
    Build an approved H4 gate decision on T04, with any field replaced from ``kw``.
    """
    base = dict(
        decision_id="g-2",
        gate=c.Gate.H4,
        stage=c.Stage.RECONCILE,
        job_ids=["T04"],
        outcome=c.GateOutcome.APPROVE,
        reviewer="r",
        shown_at=T0,
        decided_at=T0,
    )
    base.update(kw)
    return c.GateDecision(**base)


def test_gate_approval_with_warnings_needs_a_reason() -> None:
    with pytest.raises(ValidationError, match="written reason"):
        _gate(warnings=["2 heal attempts"])


def test_gate_must_match_its_stage_and_h5_is_per_wave() -> None:
    with pytest.raises(ValidationError, match="closes stage"):
        _gate(gate=c.Gate.H1, stage=c.Stage.OPERATE)
    with pytest.raises(ValidationError, match="per wave"):
        _gate(gate=c.Gate.H5, stage=c.Stage.OPERATE, job_ids=["T01", "T04"])
    assert _gate(gate=c.Gate.H5, stage=c.Stage.OPERATE, job_ids=["T01", "T04"], wave=1).wave == 1


def test_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        _gate(shown_at=datetime(2026, 11, 10, 9, 0))


def test_review_seconds() -> None:
    """
    Review time runs from showing the evidence to the decision.
    """
    assert examples()[c.GateDecision].review_seconds == 95.0


def test_accepted_literals_need_a_reason() -> None:
    """
    An unexplained literal blocks H3 until someone accepts it with a reason.
    """
    with pytest.raises(ValidationError, match="needs a reason"):
        c.LiteralFinding(value="42", line=3, provenance="none", accepted_by="reviewer")
    literal = c.LiteralFinding(value="42", line=3, provenance="none")
    assert literal.blocks_h3
    accepted = c.LiteralFinding(
        value="42",
        line=3,
        provenance="none",
        accepted_by="reviewer",
        reason="ageing threshold from the business",
    )
    assert not accepted.blocks_h3


def test_table_rows_have_one_value_per_column() -> None:
    with pytest.raises(ValidationError, match="do not have 2 values"):
        c.TableRows(table="stg.claims", columns=["a", "b"], rows=[["1"]])


def test_resolved_escalation_says_how() -> None:
    with pytest.raises(ValidationError, match="how it was resolved"):
        c.Escalation(
            escalation_id="E",
            job_id="T05",
            stage=c.Stage.RECONCILE,
            reason="error",
            diagnosis="x",
            created_at=T0,
            resolved_at=T0,
        )


def test_inventory_yaml_round_trip_keeps_dates_as_text() -> None:
    inventory = examples()[c.EstateInventory]
    text = dump_inventory(inventory)
    parsed = parse_yaml(text)
    assert parsed["jobs"][1]["invocations"][0]["params"]["SnapshotDate"] == "2025-06-30"
    assert c.EstateInventory.model_validate(parsed) == inventory


def test_yaml_has_no_yaml11_surprises() -> None:
    # plain YAML 1.1 would give False, 90, 8, a date and True for a, b, c, d and h
    parsed = parse_yaml("a: NO\nb: 1:30\nc: 010\nd: 2025-12-31\ne: true\nf: 12\ng: 0.5\nh: yes")
    assert parsed == {
        "a": "NO",
        "b": "1:30",
        "c": "010",
        "d": "2025-12-31",
        "e": True,
        "f": 12,
        "g": 0.5,
        "h": "yes",
    }
