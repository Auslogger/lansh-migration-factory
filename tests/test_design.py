"""
Design builds each output's contract from the DDL and the golden output, and H2's checks hold.
"""

from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from lansh.config import REPO_ROOT
from lansh.contracts import (
    ColumnTag,
    ComparisonPolicy,
    LineageEdge,
    LineageKind,
    PolicyKind,
    TrapFinding,
)
from lansh.design.contract import (
    build_contract,
    column_tags,
    ddl_primary_key,
    identity_columns,
    profile,
    validate,
)
from lansh.discover.job import discover_job
from lansh.estate.inventory import load_inventory
from lansh.lakehouse import golden_table, input_schemas
from lansh.llm.gateway import ClaudeGateway


def legacy(job_id: str) -> str:
    """
    Read a job's legacy code.
    """
    return (REPO_ROOT / load_inventory().job(job_id).path).read_text(encoding="utf-8")


def test_ddl_keys_and_identity_columns() -> None:
    assert ddl_primary_key(legacy("T04"), "rpt.claims_summary") == ["claim_id"]
    assert ddl_primary_key(legacy("T06"), "rpt.loss_triangle_paid") == ["accident_year", "lob_code"]
    assert identity_columns(legacy("T02"), "dw.dim_policy") == ["policy_sk"]
    assert ddl_primary_key(legacy("T04"), "rpt.nope") == []


def test_candidate_keys_come_from_the_golden_output() -> None:
    inventory = load_inventory()
    t02 = pq.read_table(golden_table(inventory, "dw.dim_policy").path)
    # the IDENTITY primary key gives way to the business key of a type-2 dimension
    keys = profile(t02, skip=["load_ts", "policy_sk"]).candidate_keys
    assert keys[0] == ["policy_id", "valid_from"]
    s04 = pq.read_table(golden_table(inventory, "rpt.risk_scores").path)
    assert profile(s04).candidate_keys == [["customer_id", "lob_code"]]  # SAS ids are doubles
    t04 = pq.read_table(golden_table(inventory, "rpt.claims_summary").path)
    # amounts are never keys, even when unique by chance
    assert profile(t04, preferred=["claim_id"]).candidate_keys == [["claim_id"], ["claim_number"]]


@pytest.fixture(scope="module")
def t04_draft():
    """
    Design T04's contract from the recorded answers.
    """
    inventory = load_inventory()
    job = inventory.job("T04")
    gateway = ClaudeGateway(mode="replay")
    found = discover_job(job, inventory, gateway)
    return build_contract(
        job,
        inventory,
        "rpt.claims_summary",
        found.lineage,
        input_schemas(inventory, job),
        found.traps,
        gateway,
    )


def test_t04_contract(t04_draft) -> None:
    contract = t04_draft.contract
    assert (contract.table, contract.layer.value, contract.keys) == (
        "gold.claims_summary",
        "gold",
        ["claim_id"],
    )
    assert contract.non_exact() == []  # no silent tolerances
    assert contract.sla is not None
    assert contract.sla.expected_rows == 823
    assert t04_draft.blockers == []


def test_h2_refuses_a_tolerance_with_no_reason(t04_draft) -> None:
    """
    The demo's H2 moment: T04 passes status through, so ci_rtrim on it is refused.
    """
    inventory = load_inventory()
    job = inventory.job("T04")
    data = pq.read_table(golden_table(inventory, "rpt.claims_summary").path)
    contract = t04_draft.contract.model_copy(deep=True)
    contract.column("status").policy = ComparisonPolicy(
        kind=PolicyKind.CI_RTRIM, reason="SQL Server column under a CI collation"
    )
    blockers, _ = validate(contract, job, data, volatile=[], identity=[], traps=[])
    assert len(blockers) == 1
    assert "tolerance with no reason" in blockers[0]
    # only text sorted under a collation (TSQL-19) would justify it
    sorting = TrapFinding(
        job_id="T04",
        trap_id="TSQL-19",
        line_start=1,
        line_end=1,
        snippet="",
        detector="llm",
        confidence=0.9,
    )
    blockers, warnings = validate(contract, job, data, volatile=[], identity=[], traps=[sorting])
    assert blockers == []
    assert any("ci_rtrim" in w for w in warnings)


def test_h2_checks_each_policy_kind() -> None:
    inventory = load_inventory()
    t02 = inventory.job("T02")
    s04 = inventory.job("S04")
    data = pa.table({"k": [1, 1], "v": [1.0, 2.0], "s": ["a", "b"]})
    from lansh.contracts import ContractColumn, DataContract

    def contract(job_id: str, keys: list[str], **policies: ComparisonPolicy) -> DataContract:
        """
        A three-column contract with the given policies.
        """
        return DataContract(
            job_id=job_id,
            table="silver.x",
            legacy_table="dw.x",
            layer="silver",
            grain="test",
            keys=keys,
            columns=[
                ContractColumn(name="k", data_type="int"),
                ContractColumn(
                    name="v", data_type="double", policy=policies.get("v", ComparisonPolicy())
                ),
                ContractColumn(
                    name="s", data_type="string", policy=policies.get("s", ComparisonPolicy())
                ),
            ],
        )

    float_rel = ComparisonPolicy(kind=PolicyKind.FLOAT_REL, rel_tolerance=1e-9, reason="SAS double")
    exclude = ComparisonPolicy(kind=PolicyKind.EXCLUDE, reason="audit")
    blockers, _ = validate(
        contract("T02", ["k"], v=float_rel, s=exclude),
        t02,
        data,
        volatile=[],
        identity=[],
        traps=[],
    )
    assert (
        len(blockers) == 3
    )  # key not unique, float_rel on T-SQL, exclude on a non-volatile column
    blockers, warnings = validate(
        contract("S04", [], v=float_rel), s04, data, volatile=[], identity=[], traps=[]
    )
    assert blockers == []
    assert any("multiset" in w for w in warnings)


def test_tags_follow_the_lineage_from_job_to_job() -> None:
    inventory = load_inventory()
    t01, s04 = inventory.job("T01"), inventory.job("S04")
    edge = {"kind": LineageKind.DERIVES, "source": "llm", "input_column": "date_of_birth"}
    into_t01 = LineageEdge(
        job_id="T01",
        output_table="dw.dim_customer",
        output_column="date_of_birth",
        input_table="stg.customers",
        **edge,
    )
    tags = column_tags([into_t01], input_schemas(inventory, t01), "dw.dim_customer")
    assert tags == {"date_of_birth": [ColumnTag.PII, ColumnTag.PROTECTED]}
    # S04 reads T01's output: the tags come with it once T01's contract carries them
    from lansh.contracts import ContractColumn, DataContract
    from lansh.lakehouse import output_columns

    t01_contract = DataContract(
        job_id="T01",
        table="silver.dim_customer",
        legacy_table="dw.dim_customer",
        layer="silver",
        grain="one row per customer",
        keys=["customer_id"],
        columns=[
            ContractColumn(**c.model_dump(exclude={"tags"}), tags=tags.get(c.name, []))
            for c in output_columns(inventory, "dw.dim_customer")
        ],
    )
    into_s04 = LineageEdge(
        job_id="S04",
        output_table="rpt.risk_scores",
        output_column="age",
        input_table="dw.dim_customer",
        **edge,
    )
    inputs = input_schemas(inventory, s04, {"dw.dim_customer": t01_contract})
    assert column_tags([into_s04], inputs, "rpt.risk_scores") == {
        "age": [ColumnTag.PII, ColumnTag.PROTECTED]
    }
