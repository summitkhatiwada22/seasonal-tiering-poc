# Probes of 2026-10-30 (exploratory)

These scripts and outputs back the research document "Improving the numbers: research and new plan" and [docs/PHASE5_PLAN.md](../../../docs/PHASE5_PLAN.md). They are **not results**: they use data up to 2022 only, nothing from 2023, and nothing from the sealed years. They were written before round two was approved and are committed so every number in the plan can be rerun.

Run from the repository root, for example `uv run python scripts/probes/2026-10-30/rolling_score.py D1`. Each script writes into `outputs/`. The monkeypatching of the planner (bulk restore speed, pooled and true-rate forecasts) lives in the scripts; no file under `src/` was changed.

| Script | Question | Output |
| --- | --- | --- |
| `forecast_diag.py` | How good are simple 30-day forecasts, and is there a season? | `forecast_diag.json` |
| `bulk_test.py` | What if forecast restores use AWS bulk speed? (tuning year 2022) | `bulk_std_*.csv`, `bulk_bulk_*.csv` |
| `rolling_test.py` | The same, picked on 2021 and scored on 2022 | `roll21_*.csv` |
| `rolling_score.py` | Phase 4 matched-waiting rule on the rolling years | printed table |
| `rolling_score_budget.py` | Equal 1% waiting allowance on the rolling years | printed table |
| `pooled_planner_test.py`, `pooled_bulk_test.py` | Planner with a pooled rate forecast, standard and bulk restores | `pooled_*.csv`, `pooledbulk_*.csv` |
| `rate_oracle_test.py`, `rate_oracle_bulk_test.py` | Planner told the true expected rate (the forecastable ceiling) | `rateoracle_*.csv`, `rateoraclebulk_*.csv` |
| `compare_all.py`, `compare_bulk.py`, `compare_planner.py`, `bulk_clean.py`, `bulk_matched.py` | Tables comparing the outputs with the saved Phase 4 tuning results in `reports/e1/central/` | printed tables |

Known limits: the probes score in-sample on 2022 unless a script says rolling; ours has more settings than the rival, so the in-sample gaps flatter ours (plan rule 5).
