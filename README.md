# LANSH

**A reconciliation-first agentic migration factory.** Team LANSH's entry to the EXL × Trinity
Data & AI Hackathon 2026, Challenge 03: agentic data platform modernisation.

LANSH migrates legacy T-SQL (SQL Server) and SAS jobs to PySpark on a Delta lakehouse, and
proves for every job that the new output matches the legacy output record for record:
counts, totals and every row, bugs included. Legacy bugs are reproduced exactly and flagged
for a human decision, and a person signs off at each of the five stages (Discover, Design,
Generate, Reconcile, Operate).

> **Status:** Phases 0 and 1 are built: the foundations, and the legacy estate with its
> ground truth. Gates G1 and G2 are awaiting review in [docs/gates.md](docs/gates.md). The
> master plan is [docs/PLAN.md](docs/PLAN.md); its step tracker (Appendix D) shows progress.

## Where things are

| Path | What |
|---|---|
| [AGENTS.md](AGENTS.md) | Working rules for everyone on the repo, AI agents included |
| [docs/PLAN.md](docs/PLAN.md) | The master plan: steps, gates, contracts, trap cards, planted bugs |
| [docs/gates.md](docs/gates.md) | Gate review packets |
| [docs/tutorial.md](docs/tutorial.md) | A beginner's guide to the ideas behind LANSH |
| [estate/](estate/README.md) | The legacy estate LANSH migrates: jobs, source data, golden outputs |
| `src/lansh/` | The factory (Python package and the `lansh` command) |
| `tests/` | pytest suites |
| [spikes/](spikes/README.md) | Phase 0 feasibility spikes and what they found |
| `scripts/` | The environment smoke test and the third-party licence list |
| `runs/` | Run output; recorded Claude answers (`runs/cassettes/`) are committed |
| `compose.yaml` | SQL Server 2022, the engine for the legacy T-SQL jobs |

## Quick start

```bash
make setup     # Python 3.14 and dependencies with uv
make check     # lint and offline tests
make smoke     # environment smoke test
```

Everything except capturing golden outputs works offline, from the committed data, golden
outputs and recorded Claude answers.

## Setup

Every development machine follows these steps (plan step 0.1). Steps 4 and 5 are only needed
on the machine that captures golden outputs from the legacy engines. Tested on macOS 15
(Apple Silicon) with Homebrew.

### 1. Java 21

Spark, Delta and saspy all run on Java 21 (plan decision L4).

```bash
brew install openjdk@21
```

The Makefile sets `JAVA_HOME` to `/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home`
for every target, and `lansh.spark` falls back to it, so you don't have to change your shell.
On other machines, set `LANSH_JAVA_HOME` to your Java 21 home. Note that
`/usr/libexec/java_home` doesn't find Homebrew JDKs.

### 2. uv and the Python packages

```bash
brew install uv
make setup        # uv sync: Python 3.14 plus every pinned dependency; creates .env
```

Pins that matter: `pyspark==4.2.0` (delta-spark 4.4.1 supports nothing newer),
`delta-spark==4.4.1`, `pandas>=2.3,<3`. SQL Server is reached with `pymssql`; `pyodbc` would
need system ODBC libraries.

### 3. Claude Code CLI

LANSH's agents call Claude through Claude Code's non-interactive mode (`claude -p`) on our
existing subscription. There is no API key and no API bill.

```bash
brew install --cask claude-code   # installs /opt/homebrew/bin/claude
claude                            # log in once with your Claude subscription, then /exit
```

- Don't set `ANTHROPIC_API_KEY` for LANSH. The gateway removes it from the environment of
  every call anyway, and never uses `--bare` (which only accepts an API key).
- If `claude` isn't on your `PATH`, set `LANSH_CLAUDE_BIN` in `.env`.

### 4. SQL Server 2022 (golden-capture machine only)

SQL Server runs in a container. On Apple Silicon it runs the amd64 image under Rosetta.

```bash
softwareupdate --install-rosetta --agree-to-license   # once
brew install orbstack                                  # or any Docker runtime
open -a OrbStack
```

Set `MSSQL_SA_PASSWORD` in `.env` (8+ characters with upper case, lower case, digits and
symbols), then:

```bash
make legacy-up     # docker compose up -d --wait, using compose.yaml
```

- The container is `lansh-sql` on port 1433, with collation `SQL_Latin1_General_CP1_CI_AS`
  and its data in the Docker volume `lansh-sql-data`.
- **SQL Server reads the SA password only when the volume is first created.** To change it
  later, run `ALTER LOGIN sa WITH PASSWORD = '...'` and update `.env` to match.
- `make legacy-down` stops it and keeps the volume.

### 5. SAS OnDemand for Academics (golden-capture machine only)

1. Create a free account at <https://welcome.oda.sas.com/>. Note your user ID and your home
   region.
2. Create `~/.config/saspy/sascfg_personal.py`:

   ```python
   SAS_config_names = ["oda"]
   oda = {
       "java": "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java",
       "iomhost": ["odaws01-euw1.oda.sas.com", "odaws02-euw1.oda.sas.com"],  # Europe
       "iomport": 8591,
       "authkey": "oda",
       "encoding": "utf-8",
   }
   ```

   Use the `iomhost` names for your region from the saspy documentation (the Europe hosts are
   shown).
3. Create `~/.authinfo` with one line, `oda user YOUR_USER_ID password YOUR_PASSWORD`, then
   `chmod 600 ~/.authinfo`.

If saspy stops connecting, the paste route in plan §7.3 is the fallback.

### 6. Smoke test

```bash
make smoke
```

Expect five lines starting `OK`:

- **Spark + Delta**: Spark 4.2.0 on Java 21, `7/2 = 3.5`, case- and space-insensitive match `True`
- **sqlglot**: `SELECT * FROM claims LIMIT 5`
- **SQL Server**: version 16.0.x, collation `SQL_Latin1_General_CP1_CI_AS`, `7/2 = 3`
- **Claude Code**: `7/2 = 3 via the subscription` with an API-equivalent cost that isn't billed
- **SAS OnDemand**: `INTCK=1`

On machines that skip steps 4 and 5 that's expected: SQL Server prints `FAIL` (there's no
server to connect to), and SAS prints `SKIP` (no saspy config). A `SKIP` doesn't fail the
smoke test.

### 7. Day to day

```bash
make check        # ruff + offline tests; must pass before merging
make test-mssql   # integration tests against SQL Server
make test-sas     # integration tests against SAS OnDemand
make test-live    # tests that make live Claude calls (uses subscription quota)
make help         # every target
```

## Data statement

All data is **100% synthetic**, produced by a seeded generator with fictional Irish names and
addresses (Faker `en_IE`) and `.example` email addresses. There is no personal data anywhere.

## AI usage and third-party software

The AI tools used to build LANSH, and the ones inside it, are declared in
[AI_USAGE.md](AI_USAGE.md). Third-party packages, services and their licences are listed in
[THIRD_PARTY.md](THIRD_PARTY.md).
