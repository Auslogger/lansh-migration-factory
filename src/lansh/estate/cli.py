"""
The ``lansh estate`` commands: synthetic data, the legacy database and golden outputs.

These are estate and evaluation tooling, not factory code: ``checks`` reads the answer key in
``estate/labels/``. They live in the estate package so the factory-isolation test can keep
every other module away from the answer key. Each command imports what it needs when it runs.
"""

from __future__ import annotations

import typer

from lansh.config import LEGACY_DATABASE

estate_app = typer.Typer(
    help="The legacy estate: synthetic data, the legacy database and golden outputs.",
    no_args_is_help=True,
)


@estate_app.command("generate")
def estate_generate(
    seed: int | None = typer.Option(None, help="Override the seed (default: the committed seed)."),
    csv: bool = typer.Option(True, help="Also write CSV copies to estate/data/csv/."),
) -> None:
    """
    Generate the synthetic insurer's nine source extracts (deterministic).
    """
    from lansh.estate import generate as gen

    # only a missing --seed means the committed one; 0 is a seed like any other
    seed = gen.SEED if seed is None else seed
    tables = gen.generate(seed=seed)
    for fp in gen.write(tables, seed=seed, csv=csv):
        typer.echo(f"{fp.table:28} {fp.rows:>8,} rows  {fp.content_sha256[:16]}")


@estate_app.command("ddl")
def estate_ddl() -> None:
    """
    Regenerate the stg table DDL from the data dictionary.
    """
    from lansh.estate.legacy import write_ddl

    typer.echo(f"wrote {write_ddl()}")


@estate_app.command("load")
def estate_load(
    database: str = typer.Option(LEGACY_DATABASE, help="Legacy database to (re)create."),
) -> None:
    """
    Recreate the legacy database and load the source extracts into SQL Server.
    """
    from lansh.estate.legacy import load_database

    counts = load_database(database)
    typer.echo(f"loaded {sum(counts.values()):,} rows into {database} (hashes verified)")


@estate_app.command("golden")
def estate_golden(
    job: list[str] = typer.Option(None, "--job", help="Job id(s) to capture (repeatable)."),
    all_jobs: bool = typer.Option(False, "--all", help="Capture every job in the inventory."),
    database: str = typer.Option(LEGACY_DATABASE, help="Legacy database to rebuild and use."),
) -> None:
    """
    Run legacy jobs on their real engines and capture golden outputs (rebuilds the DB).
    """
    from lansh.estate.golden import capture

    if not (job or all_jobs):
        raise typer.BadParameter("give --job ID (repeatable) or --all")
    for manifest in capture(None if all_jobs else list(job), database):
        for out in manifest.outputs:
            typer.echo(
                f"{manifest.job_id} {out.table:28} {out.rows:>8,} rows  {out.content_sha256[:16]}"
            )


@estate_app.command("verify")
def estate_verify(
    database: str = typer.Option(LEGACY_DATABASE, help="Legacy database to rebuild and use."),
    sas: bool = typer.Option(False, "--sas", help="Also re-run the SAS jobs (needs SAS)."),
) -> None:
    """
    Rebuild the legacy DB, re-run the T-SQL jobs and check the golden content hashes.
    """
    from lansh.estate.golden import verify, verify_sas

    results = verify(database)
    if sas:
        results |= verify_sas()
    failed = False
    for job_id, checks in results.items():
        for table, ok, detail in checks:
            failed |= not ok
            typer.echo(f"{'OK  ' if ok else 'DIFF'} {job_id} {table}: {detail}")
    if failed:
        raise typer.Exit(1)
    typer.echo(f"all {len(results)} jobs reproduced their golden hashes")


@estate_app.command("run")
def estate_run(
    job: str = typer.Option(..., "--job", help="Job id, e.g. T04 or S01."),
    database: str = typer.Option(LEGACY_DATABASE, help="Loaded legacy database (T-SQL)."),
) -> None:
    """
    Run one legacy job on its engine (development aid; does not capture goldens).
    """
    from lansh.contracts import Language
    from lansh.estate.inventory import load_inventory

    if load_inventory().job(job).language is Language.SAS:
        from lansh.estate.golden_sas import run_sas_job

        # "dev" stages the inputs in the SAS development libraries and freezes no goldens
        result = run_sas_job(job, "dev")
        for table, rows in result["outputs"].items():
            typer.echo(f"{job}: {table} {rows:,} rows")
        for line in [*result["warnings"], *result["data_notes"]]:
            typer.echo(f"  SAS: {line}")
        return
    from lansh.estate.runner import run_job

    # T-SQL: deploys the procedure and EXECs it against the already loaded database
    run = run_job(job, database)
    for table, rows in run.output_rows.items():
        typer.echo(f"{job}: {table} {rows:,} rows in {sum(run.seconds):.1f}s")


@estate_app.command("checks")
def estate_checks(
    job: str = typer.Option(..., "--job", help="Job id, e.g. T04 or S01."),
    database: str = typer.Option(LEGACY_DATABASE, help="Loaded legacy database (T-SQL)."),
) -> None:
    """
    Run a job's answer-key checks after the job has run (evaluation only).
    """
    from lansh.contracts import Language
    from lansh.estate.inventory import load_inventory

    if load_inventory().job(job).language is Language.SAS:
        from lansh.estate.golden_sas import run_sas_checks

        results = run_sas_checks(job)
    else:
        from lansh.estate.runner import run_tsql_checks

        results = run_tsql_checks(job, database)
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        typer.echo(f"{mark} {r.check_id}: affected={r.affected} {r.detail or ''}".rstrip())
    # no checks at all is a failure, not a vacuous pass
    if not results or not all(r.passed for r in results):
        raise typer.Exit(1)


@estate_app.command("score")
def estate_score(
    run: str = typer.Option(..., "--run", help="The factory run to score."),
    prove: bool = typer.Option(
        False, help="Also run the bug checks on the migrated outputs (needs SQL Server)."
    ),
    holdout: bool = typer.Option(
        False, help="A held-out run: size its planted bugs with their author's checks (SQL Server)."
    ),
) -> None:
    """
    Score a run's detection against the answer key, and prove bug reproduction (evaluation only).
    """
    import json

    from lansh.estate.scoring import write_holdout, write_scores

    if holdout:
        path = write_holdout(run)
        for check_id, rows in json.loads(path.read_text())["bug_impact"].items():
            typer.echo(f"{check_id}: the planted bug affects {rows} rows")
        typer.echo(f"wrote {path}")
        return
    path = write_scores(run, prove=prove)

    data = json.loads(path.read_text())
    for job_id, s in data["jobs"].items():
        typer.echo(
            f"{job_id}: traps {s['detected_traps']}/{s['labelled_traps']}, bugs "
            f"{s['bugs_detected']}/{s['bugs']}, findings {s['true_findings']}/{s['findings']} true"
        )
    t = data["totals"]
    typer.echo(
        f"all: traps {t['detected_traps']}/{t['labelled_traps']}, bugs {t['bugs_detected']}/"
        f"{t['bugs']}; wrote {path}"
    )


@estate_app.command("unseal")
def estate_unseal(
    confirm: bool = typer.Option(
        False,
        "--i-have-frozen-the-factory",
        help="Required: only at the factory freeze (step 3.11).",
    ),
) -> None:
    """
    Verify the held-out seal, unseal X1 and X2, and add them to the inventory (step 3.11 only).
    """
    from lansh.config import HOLDOUT_DIR, INVENTORY_PATH
    from lansh.estate.holdout import unseal
    from lansh.estate.inventory import load_inventory, parse_yaml

    if not confirm:
        raise typer.BadParameter("unseal only once the factory is frozen (plan step 3.11)")
    names = unseal(HOLDOUT_DIR)
    typer.echo(f"unsealed {len(names)} files into {HOLDOUT_DIR}: {', '.join(sorted(names))}")
    entries = parse_yaml((HOLDOUT_DIR / "jobs.yaml").read_text(encoding="utf-8"))["jobs"]
    inventory = load_inventory()
    have = {j.job_id for j in inventory.jobs}
    new = [e for e in entries if e["job_id"] not in have]
    if not new:
        typer.echo("the inventory already lists the held-out jobs")
        return
    text = INVENTORY_PATH.read_text(encoding="utf-8").rstrip("\n")
    import yaml

    block = yaml.safe_dump(new, sort_keys=False, allow_unicode=True, width=100)
    indented = "\n".join(("  " + line) if line else line for line in block.splitlines())
    text += (
        "\n\n  # Sealed held-out jobs, unsealed at the factory freeze (plan step 3.11)\n"
        + indented
        + "\n"
    )
    INVENTORY_PATH.write_text(text, encoding="utf-8")
    load_inventory()  # the merged inventory must still validate
    typer.echo(f"added {[e['job_id'] for e in new]} to {INVENTORY_PATH.name}")
