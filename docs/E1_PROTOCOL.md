# Early check E1: protocol

Written and committed on 2026-10-30, **before any real dataset was tuned or scored** (decision D-035). The code in `src/sat/experiments/` does exactly what this page says. Nothing on this page, in the policy settings (`src/sat/policies/grid.py`), the data rules or the price sheets is changed after the first 2023 run. If a bug is found after that, it is fixed, logged as a new decision, and results from before and after the fix are both reported.

## 1. Question

Does the simplest form of the idea, seasonal-naive forecasting, beat the best reactive rival by enough to justify building a real forecast (Phase 5)?

E1 is a **futility check**, lenient by design: it asks whether there is any sign worth chasing. The confirmatory test is Gate G3 in Phase 6, on the sealed 2024-2025 data, with thresholds pre-registered and tagged before that data is opened.

## 2. Data, periods and settings

**Datasets.** None of the real datasets records file sizes, so sizes come from D-032.

| Dataset | Objects | Resolution | In the decision? |
| --- | --- | --- | --- |
| D1 Wikipedia page views | 10,000 articles: cohort A most-viewed, cohort B random (D-014, D-019) | daily | yes |
| D3 npm downloads | 300 packages (D-024) | daily | yes |
| D4 Seattle library checkouts | 10,000 titles sampled from 2016-2022 (D-030) | monthly, spread over the month | yes |
| D7 synthetic, planted seasons | 10,000 | daily | no: a check of the pipeline |
| D7-control, same objects, seasons flattened | 10,000 | daily | no: a check for false wins |

D2 is not in E1. It is a size calibration with no multi-year series (D-015).

**Clouds.** AWS us-east-1, Google us-central1, and Azure East US 2 LRS, with the price sheets in `configs/prices/`. Data transfer out of the cloud is not counted: it is the same for every plan.

**Periods (D-029).**

| Run | Data the code may open | Simulated | Measured |
| --- | --- | --- | --- |
| `tune` | up to 2022 | 2021-01-01 to 2022-12-31 | 2022 |
| `eval` | up to 2023 | 2022-01-01 to 2023-12-31 | 2023 |

The first simulated year is a warm-up and is not scored. Objects are included once they exist by the end of the window (creation = first day of demand, D-031).

**Settings.** Results are judged at **central**:
- Central object sizes (IBM trace, D-032).
- Central read level: the median object is read about 18 times a year (D-031).
- Read draw seed 1.
- Restore times at the upper end of each provider's stated range.

## 3. Policies

The settings are fixed in `src/sat/policies/grid.py` and described in [POLICIES.md](POLICIES.md): 140 settings on AWS, 67 on Google and 86 on Azure. Each policy belongs to a family:
- **Rival:** `lifecycle`, `managed`, `access-lifecycle`.
- **Ours:** `seasonal`.
- **References:** `reactive`, `oracle`.

## 4. Selection on 2022

Every setting of every policy is run in the `tune` period. For each run:
- **cost** = the full bill for the measured year (all categories, including the cost of observing reads where a policy needs it).
- **cold rate** = the share of the measured year's reads that waited more than zero hours.

There are two waiting levels:

| Level | Largest cold rate allowed |
| --- | --- |
| L0 | 0: no read ever waits |
| L1 | 0.01: at most 1% of reads wait |

For every dataset, cloud and level:

1. **Rival pick:** the cheapest rival setting whose cold rate is within the level.
2. **Our pick:** the cheapest `seasonal` setting whose cold rate is within the level **and no higher than the rival pick's cold rate**.
3. **Reference pick:** the same rule for `reactive`.

Ties go to the alphabetically first policy name. If no `seasonal` setting qualifies, that line has no pick for ours and cannot pass.

The picks are written to `reports/e1/<setting>/picks.json` and **committed and pushed before any `eval` run**.

## 5. Verdict on 2023

Each picked setting is run once in the `eval` period. The central `eval` run computes every setting, because the hindsight bound and the perfect-forecast line below need them, but **only the picks from section 4 enter the decision**. For every dataset, cloud and level:

- **gap** = 1 - (our cost / rival cost), both for the measured 2023.
- The line **passes** if gap >= 0.05 **and** our 2023 cold rate is no higher than the rival's 2023 cold rate.

**Decision:**

- **CONTINUE** if at least one real dataset (D1, D3 or D4) has a passing line at the central setting, on any cloud and either level.
- **STOP AND RETHINK** otherwise.

The following are reported beside the decision but do not change it:

- **Seasonal vs reactive:** 1 - (our cost / reactive pick's cost). Near zero means any gain comes from reacting to reads, not from seasonality.
- **Perfect forecast:** the cheapest `oracle` setting in 2023 whose cold rate is no higher than the rival's.
- **Hindsight bound:** choosing, object by object and knowing 2023, the cheapest of all plans that were run, within the same waiting budget. A greedy choice is used, so this understates the true best.

  If neither this nor the perfect forecast reaches 5% on any real dataset, no forecast of this kind could pass, and the report says so.
- **Groups:** the gap inside D1 cohort A and cohort B, D1 and D3 flagged and unflagged objects (D-019), and D4 physical and digital titles.
- **D7 and D7-control:**
  - D7 should show a gain.
  - If ours passes on D7-control as well, the report must say the mechanism can win without seasonality, and how much of the real-data gap the reactive reference also achieves.

There are 18 real-data lines (3 datasets × 3 clouds × 2 levels), so one pass can occur by luck. That is acceptable for a futility check, and the report lists every line, passing or not.

## 6. Sensitivities (reported, never change the decision)

| Setting | What changes | Picks |
| --- | --- | --- |
| `size-low`, `size-high` | object sizes (D-032) | re-picked on 2022 by section 4 |
| `reads-low`, `reads-high` | read level, about 2 or 180 a year for the median object (D-031) | re-picked on 2022 by section 4 |
| `restore-low` | restore times at the lower end of each stated range | central picks, no re-picking |
| `seed-2`, `seed-3` | another random draw of reads from the same demand | central picks, no re-picking |

A central pass that disappears under `seed-2` or `seed-3` is called fragile in the report.

## 7. Commands

```bash
python -m sat.experiments run --period tune --setting central
python -m sat.experiments pick --setting central       # then commit reports/e1/central/picks.json
python -m sat.experiments run --period eval --setting central
python -m sat.experiments verdict --setting central
```

Real data is read from `data/processed/` (or `$SAT_DATA`): D1 and D3 as yearly partitions, and D4 as the sample of D-030. The sealed-year lock (D-029) refuses 2024 and later.
