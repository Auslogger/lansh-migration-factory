# LANSH

A reconciliation-first migration factory for the EXL × Trinity Data & AI Hackathon,
Challenge 03. LANSH migrates legacy T-SQL and SAS jobs to PySpark on Delta and verifies
schema, counts, totals and every row against outputs captured from the original engines.
Legacy bugs are reproduced and flagged for an explicit human decision.

## Run the demo

Install **Java 21** and **uv**, then:

```bash
make setup                 # install the pinned Python dependencies
make demo                  # replay T04, then open the Control Tower
```

On macOS with Homebrew, install the prerequisites with:

```bash
brew install openjdk@21 uv
```

On other systems install Java 21 and uv using your normal package manager. Set
`LANSH_JAVA_HOME` if Java is outside the locations in the Makefile. The first Spark run
may download its Delta JARs. Once Python dependencies and JARs are available, replay
requires no Claude login, SQL Server, SAS account or network calls to those services.
The demo normally takes about 75 seconds before opening the UI.

For the guided presentation, start here:

```bash
LANSH_DEMO_RUNS=1 uv run lansh ui
```

Open <http://localhost:8501>. Start with `showcase` → **Scorecard**, then **Job** → `T04`.
The **Demo** page opens automatically and tells the story in six steps. It includes a
**Replay the migration now** button that runs T04 through the actual pipeline. The
[recording script](docs/demo_video_script.md) gives one complete spoken paragraph per scene.
The other pages remain available for deeper inspection.

![LANSH Control Tower](docs/control_tower.png)

## Results and evidence

| Check | Recorded result |
|---|---|
| Development estate | 10/10 jobs MATCH on the first translation; 165,412 rows proved |
| Planted bugs | 8/8 reproduced; 6/8 flagged with the planted diagnosis |
| One-shot Claude | 8/10 MATCH; two outputs silently differ on 805 rows |
| One-shot plus LANSH healing | 10/10 MATCH |
| sqlglot alone | 0/10 MATCH |
| Held-out first run | 1/2 MATCH; X1 escalated at a failing trap test |
| Separate learning run | 2/2 MATCH after two generic fixes |
| Manual baseline, without AI | T05 148 minutes; S01 169 minutes; mean 158.5 minutes |

Every metric links to its source and SHA-256 in the
[scorecard](runs/showcase/scorecard.md). The business case projects onto 1,600 jobs;
review time, escalation rate and day rate are labelled assumptions. Baseline timings
come from [the manual timesheet](baseline/timesheet.csv).

Gregory Korchagin, Vansh Agarwal and Charly Martin Avila reviewed and accepted the
recorded decisions after the runs; Gregory and Vansh led most reviews. Each run's
`human_review.json` identifies the decisions, review scope, evidence and collective
reviewers. Original automated logs and timings are preserved. See the
[human review record](docs/human_reviews.md) and [build gate record](docs/gates.md).

## For judges

The final submission pack contains:

- [Submission deck, PowerPoint](docs/submission/LANSH_EXL_Submission.pptx)
- [Submission deck, PDF](docs/submission/LANSH_EXL_Submission.pdf)
- [One-page architecture](docs/submission/LANSH_Architecture_B_Control_Room.pdf)
- [One-page Responsible AI note](docs/submission/LANSH_Responsible_AI_B_Control_Room.pdf)

Useful verification commands:

```bash
make check
make test-e2e              # offline T04 pipeline through all five gates
uv run lansh audit verify --run showcase
uv run lansh audit verify --run showcase/held-out
uv run lansh audit verify --run showcase/learning
uv run lansh freeze
```

| Path | Purpose |
|---|---|
| `src/lansh/` | Factory, CLI and Control Tower source |
| `estate/` | Synthetic source data, legacy jobs, frozen goldens, labels and held-out seal |
| `migrated/` | Generated PySpark jobs, contracts and trap-focused tests |
| `runs/showcase/` | Published evidence, comparisons, human reviews and scorecard |
| `runs/showcase/held-out/` | First held-out run, including the reported escalation |
| `runs/showcase/learning/` | Separate run after the learning fixes |
| `runs/cassettes/` | Recorded model and legacy-engine answers needed for offline replay |
| `runs/freeze.json` | Factory hashes and freeze history |
| `baseline/timesheet.csv` | Measured manual migration timings |
| `tests/`, `spikes/` | Regression tests and the feasibility implementations they exercise |
| `docs/` | Final submission, architecture, review records and recording script |

Original audit entries retain source-run paths such as `runs/dev-estate/`. Their
published counterparts are in `runs/showcase/`; `dev-holdout` maps to
`showcase/held-out`, and `dev-holdout-learn` to `showcase/learning`. Comparison report
links and scorecard source hashes resolve directly within the retained files.

## Optional live runs and ground-truth capture

Replay is the default demo path. For new live model calls, install and sign in to the
Claude Code CLI, then use `--mode live`. LANSH uses `claude -p` on the team's subscription;
no API key is needed. Calls consume subscription quota.

To recapture SQL Server outputs, put `MSSQL_SA_PASSWORD` in the local `.env`, install a
Docker-compatible runtime, then run `make legacy-up`, `make load` and `make legacy-verify`.
`compose.yaml` pins the SQL Server image. SAS integration also needs a SAS OnDemand
account and local saspy configuration; see [the engine evidence](spikes/README.md).
These services are optional for the offline demo and tests.

## Scope and declarations

All data is synthetic, seeded with `20251231`, with fictional names and `.example`
email addresses. The estate was written with AI assistance, including deliberate bugs.
Results cover one reporting date, 31 December 2025. There are two held-out jobs, both
T-SQL; SAS trap tests check contracts. The recorded worker does not enforce network
isolation. These limits and the bias evidence are described in the Responsible AI note.

[AI_USAGE.md](AI_USAGE.md) declares development and product AI use.
[THIRD_PARTY.md](THIRD_PARTY.md) lists dependencies and licences.
[docs/architecture.md](docs/architecture.md) maps the local implementation to Azure.
