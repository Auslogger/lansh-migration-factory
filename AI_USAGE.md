# AI use

Team LANSH: Gregory Korchagin, Vansh Agarwal and Charly Martin Avila.

Claude Code and Codex assisted development, tests, synthetic legacy jobs, documentation
and submission preparation. LANSH's product agents use Claude through Claude Code's
non-interactive `claude -p` interface. Model outputs, usage and replay recordings are
included in the published evidence and `runs/cassettes/`.

Humans reviewed and accepted the recorded decisions after the runs. All three team
members participated; Gregory and Vansh led most reviews. Each published run includes
`human_review.json`, pinned to its original gate log. These are retrospective team
confirmations. They do not reconstruct original individual review durations or reasons.
The [review record](docs/human_reviews.md) explains the distinction.

The manual baseline was migrated by hand with AI assistants off: T05 148 minutes and
S01 169 minutes, both ending at zero reconciliation differences. Phase timings are in
`baseline/timesheet.csv`.

Data is entirely synthetic. Deliberate legacy defects are reproduced, rather than silently
fixed; suspected defects and protected flows are presented for human decisions. Model
answers must pass deterministic checks and reconciliation. See the Responsible AI PDF in
`docs/submission/` for safeguards and limitations.

Dependencies and their licences are listed in `THIRD_PARTY.md`. Original automated audit
records remain unchanged; human confirmation is stored alongside them.
