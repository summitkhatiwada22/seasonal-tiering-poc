# Seasonal Archive Tiering: Proof of Concept

**One question:** can forecasting seasonal demand keep archived data in the cheapest storage tier and bring it back *before* people ask for it, beating today's reactive auto-tiering on cost and on waiting time?

Today's cloud services look backward ("not touched for 90 days, move it down"). This project tests looking forward ("tax files will be wanted in three weeks, warm them now").

## Where we are

Run `make status` any time, or read [docs/PROGRESS.md](docs/PROGRESS.md). That file lists every phase, what is done, and the decision points where we may stop early.

| Question | Answer |
| --- | --- |
| Current phase | See `docs/PROGRESS.md` |
| Time cap | 6 weeks from 2026-10-29 (until 2026-12-10) |
| Done so far | Phases 0 to 4: foundations, data and licence checks, five real datasets downloaded and quality-checked ([Phase 2](docs/PHASE2_REPORT.md)), the cost and waiting-time simulator ([Phase 3](docs/PHASE3_REPORT.md)), and the baseline policies with early check E1 ([Phase 4](docs/PHASE4_REPORT.md)) |
| Next | Round two (approved 2026-10-30, [docs/PHASE5_PLAN.md](docs/PHASE5_PLAN.md)): stage 5a proves the restore-speed lever and the decision rule by gate R1 on Fri 6 Nov. If R1 fails, the build stops and the paper begins |
| Result so far | Early check E1 (2023 validation year): **continue** by the pre-set rule, but narrowly. Seasonal-naive beats the best rival only on Azure LRS, where no managed tiering is offered; it loses to S3 Intelligent-Tiering and Google Autoclass everywhere. The sealed test years are untouched |

## How this PoC stays honest

- **Thresholds are fixed before the test.** Pass/fail rules are written down and tagged in git before the sealed test years are read ([docs/PREREGISTRATION.md](docs/PREREGISTRATION.md) arrives in Phase 6).
- **We compare against the strongest rival**, S3 Intelligent-Tiering and Google Autoclass, not a weak baseline.
- **Every price has a receipt.** Each number in `configs/prices/` carries a link to an official AWS, Azure or Google source and the rows read are copied in [docs/evidence/](docs/evidence/official-prices-2026-10-30.md). A test fails if any price is ever marked `unverified`.
- **We test the tester.** A synthetic generator plants known seasonal patterns and a no-season control, so we can tell a real win from a false one.
- **Every result is reproducible** from raw data with one command, at a tagged commit. Data is never committed; every downloaded file is recorded with a checksum in [data_records/manifests/](data_records/manifests/).
- **Stopping is allowed.** If early checks fail, we stop and write up why.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (it installs the right Python for you).

```bash
make setup     # install pinned dependencies
make check     # lint + type check + tests (what CI runs)
make synth     # generate a small synthetic dataset
make status    # which phase are we on?
make data      # points to the real-data commands (Phase 2 runbook)
make simulate  # smoke-test the cost and waiting-time simulator on synthetic data
make e1        # early check E1: tune on 2022, pick, score on 2023 (about an hour on 2 cores)
```

The real datasets are downloaded to a folder outside the repository by following [docs/RUNBOOK_PHASE2.md](docs/RUNBOOK_PHASE2.md).

## What is in the repo

| Path | What it holds |
| --- | --- |
| `docs/PROGRESS.md` | Phase tracker and stop points |
| `docs/DECISIONS.md` | Every choice that could change results, with the reason |
| `docs/data_cards/` | One card per dataset: source, licence, caveats |
| `docs/PHASE1_REPORT.md` to `docs/PHASE4_REPORT.md` | What each finished phase found |
| `docs/SIM_RULES.md`, `docs/HAND_CALCS.md` | How prices become a bill (with official quotes) and the hand calculations the simulator must match |
| `docs/POLICIES.md`, `docs/E1_PROTOCOL.md` | Every storage policy compared, and the rules of early check E1 (fixed before the data was read) |
| `docs/RUNBOOK_PHASE2.md` | Commands to download and check the real data |
| `docs/evidence/` | Official price rows (text) and the owner's calculator screenshots |
| `configs/prices/` | AWS, Google and Azure price sheets with sources |
| `configs/datasets/` | Dataset sizes and seeds |
| `src/sat/synth/` | Synthetic data generator with ground truth |
| `src/sat/prices.py` | Price sheet loader and validator |
| `src/sat/ingest/` | Downloaders and checks for D1 to D5, checksums, quality report |
| `src/sat/sim/` | Cost and waiting-time simulator, including the billing of S3 Intelligent-Tiering and Autoclass |
| `src/sat/data/` | Loaders behind the sealed-year lock, demand-to-reads mapping, object sizes |
| `src/sat/policies/`, `src/sat/experiments/` | The policies (rivals, ours, references) and the E1 runner |
| `reports/e1/` | E1 picks, verdicts and every run's cost and waits (CSV) |
| `scripts/` and `reports/` | Phase 1 and 2 source probes and their raw outputs; the planted-bug check (`mutation_check.py`) and speed check (`bench_sim.py`) |
| `tests/` | Automated tests |
| `data_records/` | Small records of the real data: checksums, article and package lists, flags, size summaries, quality report |
| `data/` | Local data and per-object experiment arrays, git-ignored |

## Licence

The repository is public for now (decision D-012), with **no open-source licence: all rights reserved**. Reading is welcome; reuse is not permitted until a licence is chosen after the PoC result is known.
