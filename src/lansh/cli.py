"""
The ``lansh`` command line.

Sub-commands are added as each plan step lands. Each command imports what it needs when it
runs, so starting the CLI stays cheap. A command's docstring is its ``--help`` text. The
``lansh estate`` commands live in :mod:`lansh.estate.cli`, beside the estate tooling they
drive, because some of them read the answer key, which factory code must never do.
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from lansh import __version__
from lansh.config import REPO_ROOT
from lansh.estate.cli import estate_app

app = typer.Typer(
    help="LANSH: a reconciliation-first agentic migration factory.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(estate_app, name="estate")


@app.callback()
def _root(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")) -> None:
    """
    Set up logging before any command runs.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def version() -> None:
    """
    Print the LANSH version.
    """
    typer.echo(f"lansh {__version__}")


@app.command()
def template(
    job: str = typer.Option(..., "--job", help="Job id, e.g. T05."),
    out: Path | None = typer.Option(None, "--out", help="Write here instead of to stdout."),
) -> None:
    """
    Print an empty module in the job template, the starting point for a hand migration.
    """
    from lansh.estate.fingerprint import file_sha256
    from lansh.estate.inventory import load_inventory
    from lansh.generate.template import skeleton

    inventory = load_inventory()
    spec = inventory.job(job)
    text = skeleton(spec, inventory, legacy_sha256=file_sha256(REPO_ROOT / spec.path))
    if out is None:
        typer.echo(text, nl=False)
        return
    if out.exists():
        raise typer.BadParameter(f"{out} exists; not overwritten")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {out}")


@app.command()
def reconcile(
    job: str = typer.Option(..., "--job", help="Job id, e.g. T04."),
    candidate: Path | None = typer.Option(
        None, "--candidate", help="A hand-written module in the job template to check."
    ),
    keys: str | None = typer.Option(
        None, "--keys", help="Comma-separated keys to join on when there is no contract."
    ),
    samples: int = typer.Option(5, help="Sample rows per difference (0 to 5)."),
) -> None:
    """
    Run a job module on the golden inputs and reconcile its outputs record for record.
    """
    from lansh.contracts import Approach, ReconMode
    from lansh.estate.inventory import load_inventory
    from lansh.lakehouse import write_json
    from lansh.reconcile.job import new_run_id, report_markdown, run_and_reconcile, run_dir_for
    from lansh.spark import get_spark

    inventory = load_inventory()
    spec = inventory.job(job)
    module = candidate or REPO_ROOT / "migrated" / "jobs" / f"{job.lower()}.py"
    if not module.exists():
        raise typer.BadParameter(f"{module} does not exist")
    mode = ReconMode.CANDIDATE if candidate else ReconMode.ISOLATED
    run_id = new_run_id("candidate" if candidate else "reconcile")
    run_dir = run_dir_for(run_id, job)
    run = run_and_reconcile(
        get_spark(),
        inventory,
        spec,
        module,
        run_dir,
        mode=mode,
        keys=[k.strip() for k in keys.split(",")] if keys else None,
        run_id=run_id,
        approach=Approach.MANUAL if candidate else Approach.LANSH,
        sample_rows=samples,
    )
    for report in run.reports:
        write_json(run_dir / f"{report.table}.recon.json", report.model_dump(mode="json"))
        (run_dir / f"{report.table}.recon.md").write_text(report_markdown(report), "utf-8")
        typer.echo(report_markdown(report))
    took = f"worker {run.worker.seconds:.1f}s"
    typer.echo(f"{job}: {run.status.value} ({took}); reports in {run_dir}")
    if run.status.value != "MATCH":
        raise typer.Exit(1)


@app.command("run-job")
def run_job_command(
    job: str = typer.Argument(..., help="Job id, e.g. T04."),
    run: str | None = typer.Option(None, "--run", help="Run id to resume; a new run if not given."),
    reviewer: str = typer.Option(
        "agent:lansh-dev", help="person:<name> or agent:<name>; an agent's approvals are its own."
    ),
    interactive: bool = typer.Option(False, help="Ask a person at each gate in the terminal."),
    mode: str | None = typer.Option(None, help="Claude mode: replay, auto or live."),
    operate: bool = typer.Option(True, help="Run Operate (Delta and H5) after H4."),
) -> None:
    """
    Take one job through Discover, Design, Generate, Reconcile and Operate, gate by gate.
    """
    from lansh.estate.inventory import load_inventory
    from lansh.pipeline import open_run, run_job
    from lansh.reconcile.job import new_run_id

    ctx = open_run(
        run or new_run_id("job"),
        load_inventory(),
        mode=mode,
        reviewer=reviewer,
        interactive=interactive,
    )
    outcome = run_job(ctx, job, operate=operate)
    where = f" at {outcome.stopped_at.value}" if outcome.stopped_at else ""
    typer.echo(f"{job}: {outcome.status.value}{where} (run {ctx.run_id})")
    if outcome.message:
        typer.echo(f"  {outcome.message}")
    if outcome.metrics:
        m = outcome.metrics
        typer.echo(
            f"  {m.duration_seconds:.0f}s, {m.llm_calls} Claude calls ({m.llm_live_calls} live), "
            f"${m.cost_usd_equivalent:.2f} API-equivalent, {m.heal_attempts} heal attempts"
        )
    typer.echo(f"  evidence: {outcome.evidence}")
    if outcome.status.value != "MATCH" or outcome.stopped_at:
        raise typer.Exit(1)


@app.command("run")
def run_command(
    all_jobs: bool = typer.Option(
        False, "--all", help="Every development job (held-out jobs run only when named)."
    ),
    job: list[str] = typer.Option(None, "--job", help="Job id(s) to run (repeatable)."),
    run: str | None = typer.Option(None, "--run", help="Run id to resume; a new run if not given."),
    reviewer: str = typer.Option("agent:lansh-dev", help="person:<name> or agent:<name>."),
    interactive: bool = typer.Option(False, help="Ask a person at each gate in the terminal."),
    mode: str | None = typer.Option(None, help="Claude mode: replay, auto or live."),
    operate: bool = typer.Option(True, help="Cut each wave over on the lakehouse (H5)."),
) -> None:
    """
    Take the estate through the factory wave by wave, cutting each wave over together.
    """
    from lansh.estate.inventory import load_inventory
    from lansh.pipeline import open_run, run_estate
    from lansh.reconcile.job import new_run_id

    if not (all_jobs or job):
        raise typer.BadParameter("give --all or --job ID (repeatable)")
    ctx = open_run(
        run or new_run_id("estate"),
        load_inventory(),
        mode=mode,
        reviewer=reviewer,
        interactive=interactive,
    )
    result = run_estate(ctx, None if all_jobs else list(job), operate=operate)
    for number, wave in enumerate(result.waves, 1):
        for job_id in wave:
            o = result.jobs[job_id]
            where = f" at {o.stopped_at.value}" if o.stopped_at else ""
            cost = f"${o.metrics.cost_usd_equivalent:.2f}" if o.metrics else ""
            typer.echo(f"wave {number} {job_id}: {o.status.value}{where} {cost}")
    typer.echo(f"waves cut over: {result.cut_over}; run {ctx.run_id}")


@app.command()
def approve(
    run: str = typer.Option(..., "--run", help="The run with the pending gate."),
    job: str = typer.Option(..., "--job", help="The job, e.g. T04."),
    gate: str = typer.Option(..., "--gate", help="H1 to H5."),
    reviewer: str = typer.Option(..., help="person:<name>"),
    reason: str | None = typer.Option(None, help="Required with warnings or a rejection."),
    reject: bool = typer.Option(False, help="Reject instead of approving."),
) -> None:
    """
    Record a decision on a gate a run is waiting at, after showing its evidence.
    """
    import json

    from lansh.config import RUNS_DIR
    from lansh.pipeline import approve_pending

    pending = RUNS_DIR / run / "pending" / f"{job}-{gate}.json"
    if not pending.exists():
        raise typer.BadParameter(f"no pending {gate} for {job} in run {run}")
    data = json.loads(pending.read_text(encoding="utf-8"))
    typer.echo(f"{gate} for {job}: {data['summary']}")
    for e in data["evidence"]:
        typer.echo(f"  evidence: {e['ref']} ({(e.get('sha256') or '')[:12]})")
    for w in data["warnings"]:
        typer.echo(f"  WARNING: {w}")
    decision = approve_pending(run, pending, reviewer, reason, approve=not reject)
    typer.echo(f"recorded {decision.outcome.value} by {decision.reviewer} ({decision.decision_id})")


@app.command()
def benchmark(
    run: str = typer.Option(..., "--run", help="The factory run whose contracts to compare under."),
    approach: list[str] = typer.Option(
        None,
        "--approach",
        help="sqlglot_only, oneshot_claude and/or oneshot_claude+heal (default: the first two).",
    ),
    job: list[str] = typer.Option(None, "--job", help="Job id(s); every job in the run if none."),
    mode: str | None = typer.Option(None, help="Claude mode for the one-shot run."),
) -> None:
    """
    Reconcile the comparison approaches (sqlglot alone, one-shot Claude, one-shot then heal).
    """
    from lansh.benchmark import ONESHOT_HEALED, heal_oneshot, run_approach, write_benchmark
    from lansh.contracts import Approach, DataContract
    from lansh.estate.inventory import load_inventory
    from lansh.pipeline import open_run

    ctx = open_run(run, load_inventory(), mode=mode)
    contracts = {}
    for path in sorted((ctx.run_dir).glob("*/contracts/*.json")):
        contract = DataContract.model_validate_json(path.read_text(encoding="utf-8"))
        contracts[contract.legacy_table] = contract
    jobs = list(job or []) or sorted(
        {p.parent.parent.name for p in ctx.run_dir.glob("*/contracts/*.json")}
    )
    results = []
    for a in approach or ["sqlglot_only", "oneshot_claude"]:
        if a == ONESHOT_HEALED:
            results += heal_oneshot(ctx, jobs, contracts)
        else:
            results += run_approach(ctx, Approach(a), jobs, contracts)
    path = write_benchmark(run, results)
    for r in results:
        typer.echo(f"{r.approach:15} {r.job_id}: {r.status} {r.note[:100]}")
    typer.echo(f"wrote {path}")


@app.command()
def scorecard(
    run: str = typer.Option(..., "--run", help="The run to score."),
    holdout: str | None = typer.Option(None, help="The held-out jobs' run, reported apart."),
    learning: str | None = typer.Option(
        None, help="The held-out jobs' run after post-freeze fixes, reported apart."
    ),
) -> None:
    """
    Write a run's scorecard and business case, every number traced to its artifacts.
    """
    from lansh.scorecard import build, write

    card = build(run, holdout_run=holdout, learning_run=learning)
    json_path, md_path = write(card)
    for m in card.metrics:
        typer.echo(f"{m.name}: {m.value} {m.unit or ''}")
    typer.echo(f"wrote {json_path} and {md_path}")


@app.command()
def ui(port: int = typer.Option(8501, help="Port to serve the Control Tower on.")) -> None:
    """
    Open the Control Tower in a browser (Streamlit).
    """
    import subprocess
    import sys

    app_path = Path(__file__).parent / "ui" / "app.py"
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port),
         "--browser.gatherUsageStats", "false"],
        check=False,
    )  # fmt: skip


OUTSIDE_FACTORY = (
    "ui",
    "cli.py",
    "evidence.py",
    "scorecard.py",
    "benchmark.py",
    "estate/cli.py",
    "estate/scoring.py",
)
"""Reporting, scoring and the front-ends, which decide no job's outcome."""


def factory_files() -> dict[str, str]:
    """
    Hash each file of the factory: every module, prompt and trap card that decides a job's outcome.

    The command line, the Control Tower, the reports, the comparison runs and the scoring
    (``OUTSIDE_FACTORY``) are left out, so they can still change after the freeze.

    Returns:
        Each file's SHA-256, by its path inside the package.
    """
    import hashlib

    root = Path(__file__).parent
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if (
            path.is_file()
            and path.suffix in (".py", ".yaml")
            and "__pycache__" not in path.parts
            and not any(rel == part or rel.startswith(part + "/") for part in OUTSIDE_FACTORY)
        ):
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def factory_sha256() -> tuple[str, int]:
    """
    Hash the whole factory at once, over each file's path and bytes in path order.

    Returns:
        The SHA-256 and the number of files.
    """
    import hashlib

    root = Path(__file__).parent
    digest = hashlib.sha256()
    files = factory_files()
    for rel in files:
        digest.update(rel.encode() + b"\0" + (root / rel).read_bytes())
    return digest.hexdigest(), len(files)


@app.command()
def freeze(
    write: bool = typer.Option(False, help="Record the freeze in runs/freeze.json."),
    note: str = typer.Option("", help="With --write: why the factory is frozen again."),
) -> None:
    """
    Hash the factory (its code, prompts and trap library), and check it against the recorded freeze.
    """
    import json
    from datetime import UTC, datetime

    from lansh.config import RUNS_DIR

    sha, count = factory_sha256()
    files = factory_files()
    typer.echo(f"factory {sha} ({count} files)")
    path = RUNS_DIR / "freeze.json"
    frozen = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if write:
        record = {
            "factory_sha256": sha,
            "files": count,
            "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "note": note,
            "file_sha256": files,
            # every earlier freeze stays on record, the held-out run's among them
            "history": (
                [*frozen.get("history", []), {k: v for k, v in frozen.items() if k != "history"}]
                if frozen
                else []
            ),
        }
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        typer.echo(f"frozen at {record['frozen_at']}: {path}")
    elif frozen:
        if frozen["factory_sha256"] == sha:
            typer.echo(f"unchanged since the freeze at {frozen['frozen_at']}")
            return
        typer.echo(f"CHANGED since the freeze at {frozen['frozen_at']}")
        before = frozen.get("file_sha256") or {}
        for rel in sorted(set(before) | set(files)):
            if before and before.get(rel) != files.get(rel):
                typer.echo(f"  changed: {rel}")
        raise typer.Exit(1)


@app.command()
def decide(
    run: str = typer.Option(..., "--run", help="The run."),
    job: str = typer.Option(..., "--job", help="The job, e.g. T04."),
    defect: str | None = typer.Option(
        None, "--defect", help="A suspected defect's id, e.g. T04-D1."
    ),
    flow: str | None = typer.Option(None, "--flow", help="A tagged flow's id."),
    decision: str = typer.Option(
        ...,
        help="Defects: reproduce, fix_after_cutover or not_a_defect. "
        "Flows: reproduce_accepted or reproduce_flagged.",
    ),
    reviewer: str = typer.Option(..., help="person:<name>"),
    reason: str = typer.Option(..., help="Why."),
) -> None:
    """
    Record a person's decision on a suspected defect or a flow of a tagged column (H2/H4).
    """
    from lansh.config import RUNS_DIR
    from lansh.contracts import DefectDecisionKind, Gate
    from lansh.governance.gatelog import GateLog

    if bool(defect) == bool(flow):
        raise typer.BadParameter("give exactly one of --defect and --flow")
    log = GateLog(RUNS_DIR / run / "gates.jsonl")
    if defect:
        gate = Gate.H4 if log.passed(job, Gate.H2) else Gate.H2
        record = log.decide_defect(
            defect, job, DefectDecisionKind(decision), reason, reviewer, gate=gate
        )
        typer.echo(
            f"{record.defect_id}: {record.decision.value} by {record.decided_by} at {gate.value}"
        )
    else:
        flow_record = log.decide_flow(flow, decision, reason, reviewer)  # type: ignore[arg-type]
        typer.echo(f"{flow_record.flow_id}: {flow_record.decision} by {flow_record.decided_by}")


def _publish(src: Path, dest: Path, rel_from: str, rel_to: str) -> int:
    """
    Copy a run's evidence into a committed folder, leaving its bulky data behind.

    Args:
        src: The run's folder.
        dest: The folder to publish it as (replaced).
        rel_from: The run's path as its reports name it, e.g. ``runs/dev-estate/``.
        rel_to: The published path, e.g. ``runs/showcase/``.

    Returns:
        The bytes published.
    """
    import shutil

    bulky = {"staging", "outputs", "lakehouse", "__pycache__", "pending"}
    if dest.exists():
        shutil.rmtree(dest)
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if path.is_dir() or bulky & set(rel.parts) or path.suffix in (".crc", ".log"):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    from lansh.config import REPO_ROOT

    # the reports point at their run's files; the files the gate log pins stay as they were
    for name in ("evidence.json", "evidence.md", "scorecard.json", "scorecard.md"):
        for path in dest.rglob(name):
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace(rel_from, rel_to), encoding="utf-8")
    # absolute paths become repo-relative: they would publish the home folder. The gate log is
    # left byte for byte (its hash chain), and the pinned evidence hashes skip these keys
    home = str(Path.home())
    for path in dest.rglob("*"):
        if not path.is_file() or path.suffix not in (".json", ".jsonl", ".md", ".yaml"):
            continue
        text = path.read_text(encoding="utf-8")
        if path.name != "gates.jsonl" and str(REPO_ROOT) in text:
            text = text.replace(str(REPO_ROOT) + "/", "").replace(str(REPO_ROOT), ".")
            path.write_text(text, encoding="utf-8")
        if home in text:
            raise typer.BadParameter(f"{path} still names the home folder: not published")
    return sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())


@app.command()
def showcase(
    source: str = typer.Option(..., "--from", help="The run to publish as runs/showcase/."),
    holdout: str | None = typer.Option(
        None, help="The held-out run, published as runs/showcase/held-out/."
    ),
    learning: str | None = typer.Option(
        None, help="The held-out jobs' run after post-freeze fixes, as runs/showcase/learning/."
    ),
) -> None:
    """
    Copy a run's evidence into runs/showcase/ (committed), leaving its bulky data behind.
    """
    import shutil

    from lansh.config import RUNS_DIR

    src, dest = RUNS_DIR / source, RUNS_DIR / "showcase"
    if not (src / "gates.jsonl").exists():
        raise typer.BadParameter(f"run {source} has no gate log")
    size = _publish(src, dest, f"runs/{source}/", "runs/showcase/")
    typer.echo(f"published {source} as {dest} ({size / 1e6:.1f} MB)")
    for run, folder in ((holdout, "held-out"), (learning, "learning")):
        if not run:
            continue
        if not (RUNS_DIR / run / "gates.jsonl").exists():
            raise typer.BadParameter(f"run {run} has no gate log")
        size = _publish(RUNS_DIR / run, dest / folder, f"runs/{run}/", f"runs/showcase/{folder}/")
        typer.echo(f"published {run} as {dest / folder} ({size / 1e6:.1f} MB)")
    if (RUNS_DIR / "freeze.json").exists():
        # the freeze record proves the held-out run used the frozen factory
        shutil.copy2(RUNS_DIR / "freeze.json", dest / "freeze.json")


@app.command("register")
def register_command(run: str = typer.Option(..., "--run", help="The run.")) -> None:
    """
    Write a run's defect register and estate-wide flows of tagged columns from its evidence.
    """
    from lansh.config import RUNS_DIR
    from lansh.pipeline import register

    json_path, md_path = register(RUNS_DIR / run)
    typer.echo(f"wrote {json_path} and {md_path}")


@app.command("accept-literal")
def accept_literal_command(
    run: str = typer.Option(..., "--run", help="The run."),
    job: str = typer.Option(..., "--job", help="The job."),
    value: str = typer.Option(..., help="The literal, as the guardrails report it."),
    line: int = typer.Option(..., help="Its line in the module."),
    reviewer: str = typer.Option(..., help="person:<name>"),
    reason: str = typer.Option(..., help="Why it is legitimate."),
) -> None:
    """
    Accept an unexplained literal in a job's module, so H3 can be approved (a person only).
    """
    from lansh.pipeline import accept_literal

    path = accept_literal(run, job, value, line, reviewer, reason)
    typer.echo(f"recorded in {path}; run the job again to continue")


audit_app = typer.Typer(help="The gate log's audit trail.", no_args_is_help=True)
app.add_typer(audit_app, name="audit")


@audit_app.command("verify")
def audit_verify(
    run: str = typer.Option(..., "--run", help="The run whose gate log to check, e.g. showcase."),
) -> None:
    """
    Check a run's gate log: every entry must carry the hash of the entry before it.
    """
    from lansh.config import RUNS_DIR
    from lansh.governance.gatelog import GateLog

    log = GateLog(RUNS_DIR / run / "gates.jsonl")
    entries = log.entries()
    if not entries:
        raise typer.BadParameter(f"run {run} has no gate log")
    problems = log.verify()
    for problem in problems:
        typer.echo(f"BROKEN {problem}")
    if problems:
        raise typer.Exit(1)
    people = sum(d.reviewer.startswith("person:") for d in log.decisions())
    typer.echo(
        f"intact: {len(entries)} entries, {len(log.decisions())} gate decisions "
        f"({people} by people)"
    )


def main() -> None:
    """
    Run the command line; ``pyproject.toml`` installs this as the ``lansh`` script.
    """
    app()
