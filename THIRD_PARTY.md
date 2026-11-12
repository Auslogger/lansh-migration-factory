# Third-party software

LANSH reuses no third-party source code. It depends on the packages and services
below. `make third-party` rewrites the package table from installed metadata
(`scripts/third_party.py`); everything outside the table is kept up to date by hand.

## Python packages (direct dependencies)

<!-- packages:start -->
| Package | Version | Licence | Used for |
|---|---|---|---|
| datacompy | 1.2.0 | Apache Software License | runtime |
| delta-spark | 4.4.1 | Apache Software License | runtime |
| faker | 40.52.0 | MIT License | runtime |
| jinja2 | 3.1.6 | BSD License | runtime |
| networkx | 3.7 | BSD-3-Clause | runtime |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | runtime |
| pandas | 2.3.3 | BSD License | runtime |
| pyarrow | 26.0.1 | Apache-2.0 | runtime |
| pydantic | 2.14.3 | MIT | runtime |
| pymssql | 2.4.6 | LGPL-2.1 | runtime |
| pyspark | 4.2.0 | Apache-2.0 | runtime |
| pytest | 9.2.0 | MIT | dev |
| python-dotenv | 1.2.4 | BSD-3-Clause | runtime |
| pyyaml | 6.0.3 | MIT License | runtime |
| ruff | 0.17.4 | MIT | dev |
| saspy | 5.110.0 | Apache Software License | runtime |
| sqlglot | 30.30.0 | MIT | runtime |
| streamlit | 1.67.0 | Apache-2.0 | runtime |
| typer | 0.29.0 | MIT | runtime |
<!-- packages:end -->

## Downloaded at run time

| Component | Licence | Notes |
|---|---|---|
| Delta Lake JARs (`io.delta:delta-spark_2.13`, `delta-storage`) | Apache-2.0 | Fetched from Maven Central by `configure_spark_with_delta_pip` on first Spark start |
| OpenJDK 21 (Homebrew `openjdk@21`) | GPL-2.0 with Classpath Exception | Runs Spark, Delta and saspy; installed separately |

## Services and tools that are not redistributed

| Service or tool | Terms | How LANSH uses it |
|---|---|---|
| Microsoft SQL Server 2022 Developer Edition (container `mcr.microsoft.com/mssql/server`) | Microsoft EULA; Developer Edition is for development and test only | Runs the legacy T-SQL jobs to produce golden outputs. Not redistributed. |
| SAS OnDemand for Academics | SAS Institute terms of use | Runs the legacy SAS jobs to produce golden outputs. Not redistributed. |
| Claude Code CLI and Claude Opus 5.5 (Anthropic) | Anthropic consumer terms (our existing subscription) | Development assistant, and the LLM behind LANSH's agents through `claude -p`. Synthetic data only. See `AI_USAGE.md`. |
| OrbStack | OrbStack licence | Container runtime for SQL Server on Apple Silicon (any Docker runtime works) |

## Data

All data is synthetic, produced by LANSH's seeded generator with Faker's `en_IE` locale. No
third-party dataset is included.
