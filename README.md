# Seasonal Archive Tiering: Proof of Concept

**One question:** can forecasting seasonal demand keep archived data in the cheapest storage tier and bring it back *before* people ask for it, beating today's reactive auto-tiering on cost and on waiting time?

Today's cloud services look backward ("not touched for 90 days, move it down"). This project tests looking forward ("tax files will be wanted in three weeks, warm them now").

## Where we are

Run `make status` any time, or read [docs/PROGRESS.md](docs/PROGRESS.md). That file lists every phase, what is done, and the decision points where we may stop early.

| Question | Answer |
| --- | --- |
| Current phase | See `docs/PROGRESS.md` |
| Time cap | 6 weeks from 2026-10-29 (until 2026-12-10) |
| Done so far | Phases 0 to 7: foundations, data and licence checks, five real datasets downloaded and quality-checked ([Phase 2](docs/PHASE2_REPORT.md)), the cost and waiting-time simulator ([Phase 3](docs/PHASE3_REPORT.md)), the baseline policies with early check E1 ([Phase 4](docs/PHASE4_REPORT.md)), round two with gate R1 ([Phase 5](docs/PHASE5_REPORT.md)), and the pre-registered sealed test, Gate G3 ([results](docs/RESULTS.md)) |
| Next | The paper, by 2026-12-10 (D-052). The live demo and investor package are not run. Compression (Phase 8) is independent of this result and is the owner's choice |
| Result | **The proof of concept fails (Gate G3, 2026-10-30).** On the sealed years 2024 and 2025, neither the cost hypothesis (H1) nor the waiting hypothesis (H2) holds on any dataset. Seasonal forecasting on its own never beats S3 Intelligent-Tiering. A per-file choice of policy is 52-54% cheaper on Wikipedia and 39-41% on npm when up to 1% of reads may wait (some for up to 48 hours). It fails the pre-set rule because in 2024 slightly more of its reads waited than the rival's, as in gate R1. It loses on the library data in every year. On Azure it ties smart tier. Details: [docs/RESULTS.md](docs/RESULTS.md) |

## How this PoC stays honest

- **Thresholds are fixed before the test.** Pass/fail rules were written down and tagged in git (`freeze-g3`) before the sealed test years were read ([docs/PREREGISTRATION.md](docs/PREREGISTRATION.md)). The code refuses to open 2024 and 2025 unless it runs at that tag. The test failed, and is reported as failed.
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

### Re-running the sealed test

The sealed years (2024 and 2025) open only for code at the tag `freeze-g3`. With the processed data in place (`data/processed`, or the folder named by `SAT_DATA`):

```bash
git fetch --tags && git checkout freeze-g3
uv run python -m sat.experiments.g3 run --workers 2        # about 3 hours on 2 cores, all 10 scenarios
uv run python -m sat.experiments.g3 score
uv run python -m sat.experiments.g3 reproduce --workers 2  # H9: fresh clone, base scenario, compare
```

## What is in the repo

| Path | What it holds |
| --- | --- |
| `docs/PROGRESS.md` | Phase tracker and stop points |
| `docs/DECISIONS.md` | Every choice that could change results, with the reason |
| `docs/data_cards/` | One card per dataset: source, licence, caveats |
| `docs/PHASE1_REPORT.md` to `docs/PHASE5_REPORT.md` | What each finished phase found |
| `docs/R1_PROTOCOL.md`, `docs/PREREGISTRATION.md`, `docs/RESULTS.md` | Round two's rules, the sealed test's pre-registration, and its results |
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
| `src/sat/policies/`, `src/sat/experiments/` | The policies (rivals, ours, references), the per-file chooser, and the E1, R1 and G3 runners |
| `reports/e1/`, `reports/r1/`, `reports/g3/` | Picks, verdicts and every run's cost and waits (CSV) for E1, R1 and the sealed test; `reports/g3/results.json` holds the G3 verdict |
| `scripts/` and `reports/` | Phase 1 and 2 source probes and their raw outputs; the planted-bug check (`mutation_check.py`) and speed check (`bench_sim.py`) |
| `tests/` | Automated tests |
| `data_records/` | Small records of the real data: checksums, article and package lists, flags, size summaries, quality report |
| `data/` | Local data and per-object experiment arrays, git-ignored |

## Licence

The repository is public for now (decision D-012), with **no open-source licence: all rights reserved**. Reading is welcome; reuse is not permitted until a licence is chosen after the PoC result is known.
