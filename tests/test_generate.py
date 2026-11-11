"""
The synthetic insurer is deterministic and contains every planted edge case (plan §7.1).

Each test names the trap or bug whose precondition it guards (plan Appendices A and B), so a
generator change that disarms a planted condition fails here, not later in a legacy job.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from lansh.config import DATA_DIR
from lansh.estate import generate as gen
from lansh.estate.fingerprint import content_sha256, file_sha256
from lansh.estate.legacy import STG_DDL, stg_ddl

AS_OF = dt.date(2025, 12, 31)


@pytest.fixture(scope="module")
def t() -> dict[str, pd.DataFrame]:
    """
    Load the committed extracts as pandas frames of Python objects, so decimals stay exact.
    """
    return {name: tbl.to_pandas(types_mapper=None) for name, tbl in gen.read_tables().items()}


def _ci(s: pd.Series) -> pd.Series:
    """
    Normalise text the way SQL Server's = compares it, ignoring case and trailing spaces.
    """
    return s.str.rstrip(" ").str.upper()


### Determinism


def test_two_runs_produce_identical_hashes(tmp_path: Path) -> None:
    runs = []
    for k in range(2):
        out = tmp_path / f"run{k}"
        fps = gen.write(gen.generate(n_customers=600), out_dir=out, csv=True)
        runs.append({f.table: (f.file_sha256, f.content_sha256) for f in fps})
        runs[-1]["csv"] = tuple(file_sha256(p) for p in sorted((out / "csv").glob("*.csv")))
    assert runs[0] == runs[1]


def test_committed_extracts_match_the_generator() -> None:
    manifest = json.loads((DATA_DIR / "manifest.json").read_text())
    assert manifest["seed"] == gen.SEED
    assert manifest["synthetic"] is True
    fresh = gen.generate()
    for entry in manifest["tables"]:
        name = entry["table"].split(".", 1)[1]
        assert content_sha256(fresh[name]) == entry["content_sha256"], name
        assert file_sha256(DATA_DIR / f"{name}.parquet") == entry["file_sha256"], name


def test_stg_ddl_is_in_sync_with_the_dictionary() -> None:
    assert STG_DDL.read_text(encoding="utf-8") == stg_ddl(gen.load_dictionary())


def test_parquet_types_follow_the_dictionary() -> None:
    for schema in gen.load_dictionary():
        name = schema.name.split(".", 1)[1]
        arrow = pq.read_schema(DATA_DIR / f"{name}.parquet")
        assert arrow.names == [c.name for c in schema.columns]
        for col in schema.columns:
            assert arrow.field(col.name).type == gen.arrow_type(col.data_type), col.name


def test_row_seq_is_a_dense_extract_order(t: dict[str, pd.DataFrame]) -> None:
    for name, df in t.items():
        assert sorted(df["_row_seq"]) == list(range(1, len(df) + 1)), name


def test_volume_is_realistic(t: dict[str, pd.DataFrame]) -> None:
    """
    About 230,000 rows, with claims at a realistic frequency (``CLAIM_FREQUENCY``).

    Claim-side thresholds in this file are sized for that frequency: a real book has about
    one claim a year per 13 motor policies, so claim-side counts are modest.
    """
    total = sum(len(df) for df in t.values())
    assert 150_000 <= total <= 260_000
    assert len(t["claims"]) >= 2_500


def test_loss_ratios_are_realistic(t: dict[str, pd.DataFrame]) -> None:
    """
    Paid claims come to about 60-75% of earned premium overall, as in a real Irish book.

    Earned premium is approximated pro rata to the as-of date, at each currency's latest
    exchange rate; that is close enough to guard the calibration.
    """
    fx = t["fx_rates"].sort_values("rate_date").groupby("currency")["rate_to_eur"].last()
    rate = {k.strip().upper(): float(v) for k, v in fx.items()} | {"EUR": 1.0}
    x = t["premium_transactions"]
    eur = x["amount"].astype(float) * x["currency"].str.strip().str.upper().map(rate)
    start, end = pd.to_datetime(x["effective_from"]), pd.to_datetime(x["effective_to"])
    elapsed = ((pd.Timestamp(AS_OF) - start).dt.days + 1).clip(lower=0)
    earned_share = (elapsed / ((end - start).dt.days + 1)).clip(upper=1).fillna(1)
    snap = t["policy_snapshots"].drop_duplicates("policy_id").set_index("policy_id")
    lob = snap["product_code"].str.strip().str[:3].str.upper()
    earned = (eur * earned_share).groupby(x["policy_id"].map(lob)).sum()
    pay = t["claim_payments"].merge(t["claims"][["claim_id", "policy_id"]], on="claim_id")
    pay = pay[pay["payment_date"] <= AS_OF]
    paid = pay["amount"].astype(float).groupby(pay["policy_id"].map(lob)).sum()
    ratio = paid / earned
    assert ratio.between(0.35, 0.95).all(), ratio.to_dict()
    assert 0.5 <= paid.sum() / earned.sum() <= 0.85


### Synthetic-only rules


def test_contact_data_is_synthetic(t: dict[str, pd.DataFrame]) -> None:
    emails = t["customers"]["email"].dropna().str.rstrip(" ")
    assert emails.str.lower().str.endswith(".example").all()
    assert not any("phone" in c for df in t.values() for c in df.columns)


### Customers (T01, S04)


def test_bug01_customers_have_older_versions_that_differ(t: dict[str, pd.DataFrame]) -> None:
    c = t["customers"].sort_values(["customer_id", "updated_at", "_row_seq"])
    attrs = ["email", "address_line1", "town", "county", "eircode", "segment_code"]
    first = c.groupby("customer_id").head(1).set_index("customer_id")[attrs]
    last = c.groupby("customer_id").tail(1).set_index("customer_id")[attrs]
    versions = c.groupby("customer_id").size()
    multi = versions[versions > 1].index
    assert len(multi) >= 0.12 * versions.size
    differs = (first.loc[multi].fillna("<null>") != last.loc[multi].fillna("<null>")).any(axis=1)
    assert differs.sum() >= 500


def test_customer_versions_tie_on_updated_at(t: dict[str, pd.DataFrame]) -> None:
    c = t["customers"]
    ties = c.groupby(["customer_id", "updated_at"]).size()
    assert (ties > 1).sum() >= 10


def test_tsql01_emails_differ_only_in_case_or_padding(t: dict[str, pd.DataFrame]) -> None:
    c = t["customers"].drop_duplicates("customer_id", keep="last").dropna(subset=["email"])
    c = c.assign(norm=_ci(c["email"]))
    groups = c.groupby("norm")["email"].nunique()
    assert (groups > 1).sum() >= 100
    assert c["email"].str.endswith(" ").sum() >= 20


def test_tsql01_02_county_case_and_space_variants(t: dict[str, pd.DataFrame]) -> None:
    county = t["customers"]["county"].dropna()
    canonical = county.str.rstrip(" ").str.title()
    variants = county[(county != canonical)]
    assert len(variants) >= 0.03 * len(county)
    assert county.str.endswith(" ").sum() >= 100
    assert (county == county.str.upper()).sum() >= 100


def test_tsql04_age_at_join_crosses_a_birthday_boundary(t: dict[str, pd.DataFrame]) -> None:
    """
    DATEDIFF(year) counts year boundaries, so it overstates many customers' age at joining.
    """
    c = t["customers"].dropna(subset=["date_of_birth"])
    dob, since = pd.to_datetime(c["date_of_birth"]), pd.to_datetime(c["customer_since"])
    boundaries = since.dt.year - dob.dt.year
    whole = boundaries - ((since.dt.month * 100 + since.dt.day) < (dob.dt.month * 100 + dob.dt.day))
    assert (boundaries != whole).sum() >= 1_000


def test_leap_day_birthdays(t: dict[str, pd.DataFrame]) -> None:
    dob = t["customers"]["date_of_birth"].dropna()
    assert sum(1 for d in dob if d.month == 2 and d.day == 29) >= 20


def test_tsql15_eircodes_with_trailing_spaces_and_bad_lengths(t: dict[str, pd.DataFrame]) -> None:
    e = t["customers"]["eircode"]
    assert e.isna().sum() >= 300
    present = e.dropna()
    assert present.str.endswith(" ").sum() >= 200  # LEN ignores the trailing space
    assert (present.str.len() == 8).sum() >= 1_000
    assert (present.str.len() == 7).sum() >= 1_000
    assert (present.str.rstrip(" ").str.len() == 6).sum() >= 100


def test_tsql02_char_padding_in_segment_and_broker_codes(t: dict[str, pd.DataFrame]) -> None:
    assert (t["customers"]["segment_code"] == "STD ").sum() >= 1_000
    assert t["brokers"]["broker_code"].str.endswith(" ").sum() == 5


def test_irish_names_and_over_long_values(t: dict[str, pd.DataFrame]) -> None:
    c = t["customers"]
    fada = c["first_name"].str.contains("[áéíóúÁÉÍÓÚ]") | c["last_name"].str.contains(
        "[áéíóúÁÉÍÓÚ]"
    )
    assert fada.sum() >= 500
    assert c["last_name"].str.contains("'").sum() >= 100
    assert (c["last_name"].str.len() > 40).sum() >= 10
    assert (c["address_line1"].str.len() > 80).sum() >= 10
    assert c["first_name"].str.endswith(" ").sum() >= 50


### Policies (T02, T03, S03)


def test_two_policy_snapshots(t: dict[str, pd.DataFrame]) -> None:
    """
    The second snapshot keeps every policy of the first and adds new ones.
    """
    p = t["policy_snapshots"]
    s1, s2 = (set(p.loc[p["snapshot_date"] == d, "policy_id"]) for d in gen.SNAPSHOT_DATES)
    assert s1
    assert s1 < s2


def _both(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Join the policies in both snapshots on policy_id, with suffixes _1 and _2 for each one.
    """
    p = t["policy_snapshots"]
    a = p[p["snapshot_date"] == gen.SNAPSHOT_DATES[0]].set_index("policy_id")
    b = p[p["snapshot_date"] == gen.SNAPSHOT_DATES[1]].set_index("policy_id")
    return a.join(b, lsuffix="_1", rsuffix="_2", how="inner")


def test_tsql01_status_changes_only_in_case(t: dict[str, pd.DataFrame]) -> None:
    j = _both(t)
    case_only = (j["status_1"] != j["status_2"]) & (_ci(j["status_1"]) == _ci(j["status_2"]))
    assert case_only.sum() >= 50
    status = t["policy_snapshots"]["status"]
    assert (status != _ci(status)).sum() >= 0.02 * len(status)


def test_tsql06_vehicle_reg_null_versus_empty(t: dict[str, pd.DataFrame]) -> None:
    j = _both(t)
    null_to_empty = j["vehicle_reg_1"].isna() & (j["vehicle_reg_2"] == "")
    empty_to_null = (j["vehicle_reg_1"] == "") & j["vehicle_reg_2"].isna()
    assert null_to_empty.sum() >= 50
    assert empty_to_null.sum() >= 50


def test_type2_history_has_genuine_changes(t: dict[str, pd.DataFrame]) -> None:
    j = _both(t)
    changed = (
        (_ci(j["status_1"]) != _ci(j["status_2"]))
        | (j["annual_premium_1"] != j["annual_premium_2"])
        | (j["broker_code_1"].fillna("~") != j["broker_code_2"].fillna("~"))
        | (j["vehicle_reg_1"].fillna("~") != j["vehicle_reg_2"].fillna("~"))
    )
    assert changed.sum() >= 500


def test_tsql01_02_broker_codes_vary_from_the_register(t: dict[str, pd.DataFrame]) -> None:
    codes = set(t["brokers"]["broker_code"])
    keyed = t["policy_snapshots"]["broker_code"].dropna()
    exact = keyed.isin(codes)
    loose = _ci(keyed).isin({c.rstrip(" ").upper() for c in codes})
    assert loose.all()
    assert (~exact).sum() >= 0.05 * len(keyed)  # includes 5-char codes vs CHAR(6) padding


def test_tsql06_direct_business_has_no_broker(t: dict[str, pd.DataFrame]) -> None:
    assert t["policy_snapshots"]["broker_code"].isna().mean() > 0.3


def test_product_code_case_variants(t: dict[str, pd.DataFrame]) -> None:
    codes = set(t["products"]["product_code"])
    keyed = t["policy_snapshots"]["product_code"]
    assert (~keyed.isin(codes)).sum() >= 200
    assert _ci(keyed).isin(codes).all()


def test_sas12_premiums_on_band_boundaries(t: dict[str, pd.DataFrame]) -> None:
    prem = t["policy_snapshots"]["annual_premium"]
    for value in ("0.00", "500.00", "1000.00"):
        assert (prem == Decimal(value)).sum() >= 20, value


def test_bug02_cover_periods_spanning_29_february_2024(t: dict[str, pd.DataFrame]) -> None:
    x = t["premium_transactions"]
    leap = dt.date(2024, 2, 29)
    spans = (x["effective_from"] <= leap) & (x["effective_to"] >= leap)
    days = (pd.to_datetime(x["effective_to"]) - pd.to_datetime(x["effective_from"])).dt.days + 1
    assert (spans & (days == 366)).sum() >= 300
    starts = t["policy_snapshots"]["inception_date"]
    assert (starts == leap).sum() >= 2


def test_premium_transaction_types(t: dict[str, pd.DataFrame]) -> None:
    """
    All four transaction types appear, with negative amounts and case variants among them.
    """
    x = t["premium_transactions"]
    kinds = _ci(x["txn_type"]).value_counts()
    assert {"NB", "REN", "MTA", "CAN"} <= set(kinds.index)
    assert (x["amount"] < 0).sum() >= 300
    assert (x["txn_type"] != _ci(x["txn_type"])).sum() >= 50


def test_tsql18_month_end_cover_starts(t: dict[str, pd.DataFrame]) -> None:
    starts = pd.to_datetime(t["premium_transactions"]["effective_from"])
    month_end = starts.dt.is_month_end
    short_month = starts.dt.month.isin([2, 4, 6, 9, 11])
    assert month_end.sum() >= 500
    assert (~month_end & short_month).sum() >= 1_000


def test_tsql09_fx_gaps_and_revisions(t: dict[str, pd.DataFrame]) -> None:
    fx = t["fx_rates"]
    dates = set(fx["rate_date"])
    assert min(dates) == dt.date(2019, 1, 2)
    assert not ({dt.date(2024, 2, d) for d in (26, 27, 28, 29)} & dates)  # the four-day outage
    assert dt.date(2025, 12, 25) not in dates  # no rates on holidays
    assert (fx["source"] == "ECB-REV").sum() == 8
    x = t["premium_transactions"]
    foreign = x[_ci(x["currency"]) != "EUR"]
    assert (foreign["txn_date"] < dt.date(2019, 1, 2)).sum() >= 3  # no rate yet
    in_outage = foreign["txn_date"].between(dt.date(2024, 2, 26), dt.date(2024, 2, 29))
    assert in_outage.sum() >= 4
    weekend = pd.to_datetime(foreign["txn_date"]).dt.weekday >= 5
    assert weekend.sum() >= 100


### Claims (T04, T05, T06, T08)


def test_tsql01_02_claim_status_and_lob_variants(t: dict[str, pd.DataFrame]) -> None:
    c = t["claims"]
    open_ = c[_ci(c["status"]).isin(["OPEN", "REOPENED"])]
    assert (open_["status"] != _ci(open_["status"])).sum() >= 30
    assert (c["lob_code"] != _ci(c["lob_code"])).sum() >= 50


def test_tsql05_claims_without_a_handler(t: dict[str, pd.DataFrame]) -> None:
    c = t["claims"]
    open_ = _ci(c["status"]).isin(["OPEN", "REOPENED"])
    assert (c["handler_code"].isna() & open_).sum() >= 100


def test_bug03_open_claims_with_several_reserves_and_payments(t: dict[str, pd.DataFrame]) -> None:
    c, p, r = t["claims"], t["claim_payments"], t["claim_reserves"]
    open_ids = set(c.loc[_ci(c["status"]).isin(["OPEN", "REOPENED"]), "claim_id"])
    n_res = r[r["reserve_date"] <= AS_OF].groupby("claim_id").size()
    n_pay = p[(p["payment_date"] <= AS_OF) & p["amount"].notna()].groupby("claim_id").size()
    both = set(n_res[n_res >= 2].index) & set(n_pay.index) & open_ids
    assert len(both) >= 300


def test_bug04_open_claims_exactly_30_days_since_last_activity(t: dict[str, pd.DataFrame]) -> None:
    c, p = t["claims"], t["claim_payments"]
    open_ = c[_ci(c["status"]).isin(["OPEN", "REOPENED"])].set_index("claim_id")
    last_pay = p[p["payment_date"] <= AS_OF].groupby("claim_id")["payment_date"].max()
    activity = last_pay.reindex(open_.index).fillna(open_["reported_date"])
    age = pd.Series([(AS_OF - d).days for d in activity], index=activity.index)
    assert (age == 30).sum() >= 10
    # and on every band edge
    for boundary in (29, 31, 60, 61):
        assert (age == boundary).sum() >= 3, boundary


def test_bug05_payments_on_the_loss_date(t: dict[str, pd.DataFrame]) -> None:
    j = t["claim_payments"].merge(t["claims"][["claim_id", "loss_date"]], on="claim_id")
    assert (j["payment_date"] == j["loss_date"]).sum() >= 150


def test_tsql04_payments_cross_a_year_boundary_within_a_year(t: dict[str, pd.DataFrame]) -> None:
    """
    DATEDIFF(year) counts year boundaries, so it overstates the time from loss to many payments.
    """
    j = t["claim_payments"].merge(t["claims"][["claim_id", "loss_date"]], on="claim_id")
    loss, paid = pd.to_datetime(j["loss_date"]), pd.to_datetime(j["payment_date"])
    crossed = paid.dt.year - loss.dt.year
    whole = crossed - ((paid.dt.month * 100 + paid.dt.day) < (loss.dt.month * 100 + loss.dt.day))
    assert (crossed != whole).sum() >= 1_000


def test_bug07_claims_reported_soon_after_inception_and_after_expiry(
    t: dict[str, pd.DataFrame],
) -> None:
    p = t["policy_snapshots"]
    p = p[p["snapshot_date"] == AS_OF][["policy_id", "inception_date", "expiry_date"]]
    j = t["claims"].merge(p, on="policy_id")
    after_start = (pd.to_datetime(j["reported_date"]) - pd.to_datetime(j["inception_date"])).dt.days
    after_end = (pd.to_datetime(j["reported_date"]) - pd.to_datetime(j["expiry_date"])).dt.days
    assert after_start.between(0, 30).sum() >= 100
    assert after_end.between(0, 30).sum() >= 50


def test_tsql14_vehicle_registrations(t: dict[str, pd.DataFrame]) -> None:
    """
    Most registrations follow the Irish format, and at least 100 don't.
    """
    reg = t["policy_snapshots"]["vehicle_reg"].dropna()
    reg = reg[reg != ""]
    pattern = reg.str.match(r"^\d{2,3}-[A-Z]{1,2}-\d+$")
    assert pattern.mean() > 0.9
    assert (~pattern).sum() >= 100


### Payments (S01)


def test_bug08_missing_negative_and_zero_amounts(t: dict[str, pd.DataFrame]) -> None:
    amt = t["claim_payments"]["amount"]
    assert amt.isna().sum() >= 40
    assert (amt.dropna() < 0).sum() >= 60
    assert (amt.dropna() == 0).sum() >= 25


def test_sas05_orphan_payments(t: dict[str, pd.DataFrame]) -> None:
    orphans = ~t["claim_payments"]["claim_id"].isin(t["claims"]["claim_id"])
    assert orphans.sum() == 25


def test_sas06_extract_order_differs_from_payment_date_order(t: dict[str, pd.DataFrame]) -> None:
    p = t["claim_payments"].sort_values("_row_seq")
    out_of_order = p.groupby("claim_id")["payment_date"].apply(
        lambda s: (s.diff().dt.days < 0).any() if len(s) > 1 else False
    )
    assert out_of_order.sum() >= 100


def test_future_dated_rows_after_the_as_of_date(t: dict[str, pd.DataFrame]) -> None:
    assert (t["claim_payments"]["payment_date"] > AS_OF).sum() >= 10
    assert (t["claim_reserves"]["reserve_date"] > AS_OF).sum() >= 10


def test_ties_same_day_payments_and_reserve_corrections(t: dict[str, pd.DataFrame]) -> None:
    p = t["claim_payments"].groupby(["claim_id", "payment_date"]).size()
    r = t["claim_reserves"].groupby(["claim_id", "reserve_type", "reserve_date"]).size()
    assert (p > 1).sum() >= 50
    assert (r > 1).sum() >= 50


def test_tsql01_case_variant_motor_claim_with_a_bad_registration(
    t: dict[str, pd.DataFrame],
) -> None:
    """
    A recent motor claim keyed in another case has a registration the format rule rejects.

    That one row arms T08's motor test (lob_code = 'MOT'), so the generator must keep it.
    """
    p = t["policy_snapshots"]
    p = p[p["snapshot_date"] == AS_OF][["policy_id", "vehicle_reg"]]
    j = t["claims"].merge(p, on="policy_id")
    recent = j["reported_date"] > dt.date(2024, 12, 31)
    variant = (_ci(j["lob_code"]) == "MOT") & (j["lob_code"].str.rstrip(" ") != "MOT")
    reg = j["vehicle_reg"]
    bad = reg.notna() & ~reg.fillna("").str.match(r"^\d{2,3}-[A-Z]{1,2}-\d+$")
    assert (recent & variant & bad).sum() >= 1


### Consistency of the planted conditions


def test_cover_never_starts_before_its_customer_joined(t: dict[str, pd.DataFrame]) -> None:
    """
    Planted early starts (sterling lines in January 2019, BUG-02 leap-day covers) included.
    """
    since = t["customers"].groupby("customer_id")["customer_since"].min()
    p = t["policy_snapshots"].drop_duplicates("policy_id")
    assert (p["inception_date"] < p["customer_id"].map(since)).sum() == 0


def test_annual_lines_never_overlap_themselves() -> None:
    """
    No term of an annual line overlaps another term of the same line.

    The planted start dates (29 February 2024, 31 December 2023, 1 January 2024) move only a
    line's single term, so renewals never collide with it. Single trips (``TRV-SGL``) are
    separate covers and may overlap. Built in memory, because the extracts don't carry the
    line id.
    """
    s = gen.SynthInsure(n_customers=4_000)
    s.products()
    brokers = s.brokers()
    _, people = s.customers()
    terms = s.policies(people, brokers)
    lines: dict[int, list[gen.Term]] = {}
    for term in terms:
        if term.product_code != "TRV-SGL":
            lines.setdefault(term.line_id, []).append(term)
    clashes = [
        (a.policy_id, b.policy_id)
        for line in lines.values()
        for i, a in enumerate(line)
        for b in line[i + 1 :]
        if a.inception <= b.expiry and b.inception <= a.expiry
    ]
    assert clashes == []
    leap = [
        term
        for term in terms
        if term.inception == dt.date(2024, 2, 29) and len(lines[term.line_id]) == 1
    ]
    assert len(leap) >= 6


def test_claims_keyed_against_another_line_of_business(t: dict[str, pd.DataFrame]) -> None:
    """
    A few claims carry another line of business than their policy (T08's lob_mismatch_flag).
    """
    p = t["policy_snapshots"].drop_duplicates("policy_id")[["policy_id", "policy_number"]]
    j = t["claims"].merge(p, on="policy_id")
    assert (_ci(j["lob_code"]) != j["policy_number"].str[:3]).sum() >= 5
