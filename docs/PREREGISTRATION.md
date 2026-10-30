# Pre-registration: Gate G3, the sealed test

Written on **2026-10-30**, before the freeze tag `freeze-g3` exists and before any analysis has opened a file from 2024 or 2025. The tag will point at the commit that contains this file. The sealed years unlock only for code running at that exact commit (`unlock_sealed` in `src/sat/data/sealed.py`, with tests). Anything changed after the tag is exploratory and is reported as such.

## 0. Why this test is being run (a documented deviation)

Gate R1 failed on 2026-10-30 (D-050). The rule of D-038 says the build stops and the paper begins. The owner chose to override that rule, as a documented deviation (D-051):

* nothing is built or tuned after this point;
* the methods are frozen exactly as committed;
* the sealed years are opened once, by this protocol.

The sealed years have never been opened, so this remains a clean confirmatory test of a method fixed before them. It does not undo R1. The write-up reports R1 as failed and this test as run after an owner override.

## 1. What is frozen

* **Code:** the whole repository at `freeze-g3`, in particular `src/sat/experiments/{g3,r1,chooser,zrs}.py`, `src/sat/policies/` and the simulator.
* **Methods:** the 161-policy AWS grid `round2_grid` (rivals with bulk on-demand restores, ours, the reactive reference). The per-file chooser with its 21 settings, the default (Intelligent-Tiering without archive tiers) and the upper-bound switch charge. The forecastable ceiling (independent replicate draw, seed + 100). All as in `docs/R1_PROTOCOL.md` sections 3 and 4.
* **Prices:** `configs/prices/aws.yaml` and `configs/prices/azure_zrs/azure.yaml` as committed.

## 2. Data and years

* **Datasets:** D1 (Wikipedia), D3 (npm) and D4 (Seattle library sample). The three settings are the E1 central setting and the scenarios in section 5.
* **Sealed years:** 2024 and 2025. D4's 2026 rows are not used. Loaders run with `max_year = 2025`.
* **Rolling pairs:** pick on 2023 and score on 2024; pick on 2024 and score on 2025. 2022 is simulated only as the chooser's history for the 2023 pick.
* **2023:** using 2023 as a pick year is the one labelled second look at 2023 allowed by D-037.
* **Picking on 2024:** the pick on 2024 uses sealed results for 2024 only to score 2025. This is mechanical, fixed here, and is what an operator would know by 1 January 2025.
* **Files:** the sealed Parquet partitions come from the owner's flash drive, written in Phase 2 (2026-10-29): D1 and D3 `year=2024` and `year=2025`, D4_sample `year=2024` and `year=2025`. When they are copied into the workspace, their modification times and SHA-256 are recorded in `reports/g3/sealed_files.csv`. The times must predate the freeze tag.

## 3. The run (once)

```
git fetch --tags && git checkout freeze-g3        # HEAD must be the freeze commit
uv run python -m sat.experiments.g3 run --workers 2
uv run python -m sat.experiments.g3 score
uv run python -m sat.experiments.g3 reproduce --workers 2
```

For each scenario `run` simulates the actual draws of 2022 to 2025. For the base scenario it also runs the replicate draws of 2023 to 2025 and the Azure ZRS grid. `score` writes `reports/g3/<scenario>/{table,lines}.csv` and `reports/g3/results.json`. `docs/RESULTS.md` is then written from `results.json` and committed. The same commands were rehearsed on 2020 to 2022 before the freeze (`--rehearsal`, outputs in `reports/g3-rehearsal/`).

## 4. Pick rule

Identical to `docs/R1_PROTOCOL.md` section 5:

* levels L0 (no read waits) and L1 (at most 1% of reads wait);
* the rival pick is the cheapest rival meeting the level on the pick year;
* **matched** rule (decides): ours is the cheapest of ours on the pick year waiting no more than the rival pick; the line passes only if ours also waits no more than the rival in the score year;
* **equal** rule (reported only): an equal 1% allowance, with total waiting hours and the longest wait.

"Ours" means the families `seasonal` and `chooser`.

## 5. Hypotheses and thresholds

| ID | Test on the sealed years | Passes if |
| --- | --- | --- |
| H1 Cost (D-046) | Matched rule, AWS. For each dataset, at one level, both pairs: gap at least 5%, ours waits no more than the rival, and the 95% interval of the gap is above zero. The interval is a paired bootstrap over files: 2,000 resamples, seed 20261030, gap = 1 - sum(ours) / sum(rival) | Holds on at least 2 of D1, D3, D4 |
| H2 Wait | Matched rule at L1, both pairs: ours costs no more than the rival and its share of waited reads is at most half the rival's (the rival must have waited at all) | Holds on at least 2 of D1, D3, D4 ("3 of 4" corrected for the same reason as H1, D-046) |
| H3 Headroom (reported) | Base, L1: ours' gap divided by the ceiling's gap | Reported, not a pass condition |
| H4 Is a model needed (reported) | Base: ours against the seasonal-naive family alone, picked by the same rule | If ours is not 5% or more cheaper, the simple rule is what ships |
| H5 Robust | The hypothesis that passed in base (H1, or else H2), re-run in 10 scenarios: base; storage prices x0.5 and x1.5; request and retrieval fees x0.5 and x1.5; restore times at the low end; read scale low and high; sizes low and high | Holds in at least 8 of the 10 |
| H6 Net of compute | Base: core-hours of one year's grid run (the chooser's history) at USD 0.04 per core-hour (assumed; also reported at 10 times this), divided by the saving against the rival at L1 | Under 5% in both sealed years on every dataset that counts towards H1 or H2 |
| H7 Simulator trust | Gate G2 (Phase 3) | Already passed |
| H9 Reproducible | `reproduce`: a fresh clone at `freeze-g3` re-simulates the base scenario from the processed data and scores it | Every base line's rival and ours cost within 0.05% of the main run (3 significant figures) |

**The PoC passes if (H1 or H2) and H5 and H6 and H7 and H9.**

Prices in H5 scale every field of the AWS sheet of that kind:

* **storage:** every `*_per_gb_month` field, Intelligent-Tiering's included;
* **fees:** every per-1,000 request field and every per-GB retrieval or restore field, Intelligent-Tiering's monitoring included.

The Azure ZRS sheet and Google are not in H5. The original "three clouds" is reduced to AWS because round two built no Google methods. Azure is reported in section 7.

## 6. Kill and pivot rules (from the plan, applied as written)

* **H1 and H2 both fail:** stop the product thesis; the paper reports a fee-accurate benchmark and the result.
* **Only H2 passes:** the pitch is "less waiting for archived data at no extra cost", not savings.
* **H4 fails:** ship the simple rule. The chooser is already a rules engine over simulated policies.
* **H6 fails:** the method only pays at large scale; reframe the target customer.
* **H1 passes but H5 fails:** report the saving as conditional on the scenarios where it held.

## 7. Reported regardless of outcome

* Every line, both waiting rules, waiting hours and longest waits.
* Every scenario's table.
* The Azure ZRS comparison (chooser against smart tier, both pairs).
* The share of bytes and files the chooser puts in each kind of policy.

R1 is reported as failed.

## 8. Weaknesses written down before the test

* This test is run after an owner override of a failed gate (D-051).
* Reads are mapped from demand (D-031) and sizes are drawn from one trace (D-032). No customer log is involved.
* The waiting rule counts waited reads, not hours. Ours can wait up to 48 hours (bulk restores) against the rival's 12, and usually more hours in total.
* D4 showed that a regime change (2020) breaks year-on-year choice. 2024 and 2025 may contain their own.
* The switch charge is an upper bound, which is conservative for ours.
* H9 is reproduced in the same kind of workspace, not on a stranger's machine. The owner may also run `reproduce` in a fresh Codespace.
