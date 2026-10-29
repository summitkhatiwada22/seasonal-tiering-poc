# Seasonal Archive Tiering: Proof of Concept

**One question:** can forecasting seasonal demand keep archived data in the cheapest storage tier and bring it back *before* people ask for it, beating today's reactive auto-tiering on cost and on waiting time?

Today's cloud services look backward ("not touched for 90 days, move it down"). This project tests looking forward ("tax files will be wanted in three weeks, warm them now").

## Where we are

Run `make status` any time, or read [docs/PROGRESS.md](docs/PROGRESS.md). That file lists every phase, what is done, and the decision points where we may stop early.

| Question | Answer |
| --- | --- |
| Current phase | See `docs/PROGRESS.md` |
| Time cap | 6 weeks from 2026-10-29 (until 2026-12-10) |
| Result so far | None yet. Phase 0 only builds the foundations |

## How this PoC stays honest

- **Thresholds are fixed before the test.** Pass/fail rules are written down and tagged in git before the sealed test years are read ([docs/PREREGISTRATION.md](docs/PREREGISTRATION.md) arrives in Phase 6).
- **We compare against the strongest rival**, S3 Intelligent-Tiering and Google Autoclass, not a weak baseline.
- **Every price has a receipt.** Each number in `configs/prices/` says whether it is `sourced` (with a link) or `unverified` (to be checked), and tests enforce that.
- **We test the tester.** A synthetic generator plants known seasonal patterns and a no-season control, so we can tell a real win from a false one.
- **Every result is reproducible** from raw data with one command, at a tagged commit. Data is never committed; every downloaded file is recorded with a checksum in [manifests/](manifests/).
- **Stopping is allowed.** If early checks fail, we stop and write up why.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (it installs the right Python for you).

```bash
make setup     # install pinned dependencies
make check     # lint + type check + tests (what CI runs)
make synth     # generate a small synthetic dataset
make status    # which phase are we on?
```

## What is in the repo

| Path | What it holds |
| --- | --- |
| `docs/PROGRESS.md` | Phase tracker and stop points |
| `docs/DECISIONS.md` | Every choice that could change results, with the reason |
| `docs/data_cards/` | One card per dataset: source, licence, caveats |
| `configs/prices/` | AWS, Google and Azure price sheets with sources |
| `configs/datasets/` | Dataset sizes and seeds |
| `src/sat/synth/` | Synthetic data generator with ground truth |
| `src/sat/prices.py` | Price sheet loader and validator |
| `tests/` | Automated tests |
| `manifests/` | Checksums of every downloaded file (from Phase 2) |
| `data/` | Local data, git-ignored |

## Licence

Private repository, all rights reserved. A licence will be chosen after the PoC result is known.
