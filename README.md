# Seasonal Archive Tiering: Proof of Concept

**One question:** can forecasting seasonal demand keep archived data in the cheapest storage tier and bring it back *before* people ask for it, beating today's reactive auto-tiering on cost and on waiting time?

Today's cloud services look backward ("not touched for 90 days, move it down"). This project tests looking forward ("tax files will be wanted in three weeks, warm them now").

## Where we are

Run `make status` any time, or read [docs/PROGRESS.md](docs/PROGRESS.md). That file lists every phase, what is done, and the decision points where we may stop early.

| Question | Answer |
| --- | --- |
| Current phase | See `docs/PROGRESS.md` |
| Time cap | 6 weeks from 2026-10-29 (until 2026-12-10) |
| Done so far | Phases 0, 1 and 2: foundations, data and licence checks, and five real datasets downloaded and quality-checked ([Phase 2 report](docs/PHASE2_REPORT.md)) |
| Next | Phase 3: the cost and waiting-time simulator (Gate G2) |
| Result so far | None yet. No forecasting result exists; the sealed test years are untouched |

## How this PoC stays honest

- **Thresholds are fixed before the test.** Pass/fail rules are written down and tagged in git before the sealed test years are read ([docs/PREREGISTRATION.md](docs/PREREGISTRATION.md) arrives in Phase 6).
- **We compare against the strongest rival**, S3 Intelligent-Tiering and Google Autoclass, not a weak baseline.
- **Every price has a receipt.** Each number in `configs/prices/` says whether it is `sourced` (with a link) or `unverified` (to be checked), and tests enforce that.
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
```

The real datasets are downloaded to a folder outside the repository by following [docs/RUNBOOK_PHASE2.md](docs/RUNBOOK_PHASE2.md).

## What is in the repo

| Path | What it holds |
| --- | --- |
| `docs/PROGRESS.md` | Phase tracker and stop points |
| `docs/DECISIONS.md` | Every choice that could change results, with the reason |
| `docs/data_cards/` | One card per dataset: source, licence, caveats |
| `docs/PHASE1_REPORT.md`, `docs/PHASE2_REPORT.md` | What each finished phase found |
| `docs/RUNBOOK_PHASE2.md` | Commands to download and check the real data |
| `configs/prices/` | AWS, Google and Azure price sheets with sources |
| `configs/datasets/` | Dataset sizes and seeds |
| `src/sat/synth/` | Synthetic data generator with ground truth |
| `src/sat/prices.py` | Price sheet loader and validator |
| `src/sat/ingest/` | Downloaders and checks for D1 to D5, checksums, quality report |
| `scripts/` and `reports/` | Phase 1 and 2 source probes and their raw outputs |
| `tests/` | Automated tests |
| `data_records/` | Small records of the real data: checksums, article and package lists, flags, size summaries, quality report |
| `data/` | Local data, git-ignored |

## Licence

The repository is public for now (decision D-012), with **no open-source licence: all rights reserved**. Reading is welcome; reuse is not permitted until a licence is chosen after the PoC result is known.
