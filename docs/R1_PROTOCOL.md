# Gate R1 protocol (round two, stage 5a)

Written and pushed on **2026-10-30, before any real-data run of the methods below**. The code that carries it out (`src/sat/experiments/r1.py`, `src/sat/experiments/chooser.py`, `round2_grid` in `src/sat/policies/grid.py`) is in the same commit. The only data the methods were run on before this commit is the synthetic dataset D7, for development; those outputs are kept in `reports/r1/dev/` and are not part of any result. Decision D-045.

Disclosure: the 2026-10-30 probes (`scripts/probes/2026-10-30/`) already scored bulk-restore variants of the Phase 4 policies on 2021 and 2022. Those are the only earlier looks at these years with bulk restores.

## 1. Question

Does any method of ours beat the best AWS rival by enough, on years its settings did not see, to justify building further (stage 5b)? And is there enough left to win for a forecast to be worth building?

## 2. Data and years

* Real datasets D1, D3 and D4 at the E1 central setting (central sizes, central read scale, seed 1). D7 is synthetic and only used for development.
* Data are loaded **up to 2022 only**. 2023 is not opened (it was used by E1) and 2024-2025 stay sealed (D-029).
* Year Y is simulated from 1 January of Y-1 (warm-up) to 31 December of Y, measured over Y, with the reads matrix cut at the end of Y. Measured years: 2019, 2020, 2021 and 2022.
* **Rolling pairs:** pick on 2020 and score on 2021; pick on 2021 and score on 2022.
* **Draws.** `actual`: the E1 central reads (identical to E1's, checked by a test). `replicate`: an independent Poisson draw from the same true expected rates (seed + 100), for 2020-2022. Nothing is ever scored on the replicate draw.

## 3. Policies (AWS, 161, all run on every year)

`round2_grid("aws")`:

* **Rivals (19):** the 15 E1 rivals (all-Standard, lifecycle to each class after 30 or 90 days, six Intelligent-Tiering settings), plus lifecycle to Glacier Flexible or Deep Archive with on-demand restores at **bulk** speed (4). A customer can choose bulk restores, so the rival gets them too.
* **Ours, family `seasonal` (91):** the 67 E1 forms, plus bulk variants: the fee-aware planner with an archive class, pricing and making its moves up at bulk speed (12), and copy mode (keep archived, restore ahead of last year's reads) with bulk restores (12). Leads of 7 and 30 days cover the 48-hour bulk restore.
* **Reactive reference (51):** the 39 E1 forms plus the same bulk variants with the forecast switched off (12).
* The E1 oracle references are not run. The forecastable ceiling (section 4) replaces them.

## 4. The per-file chooser (the "exact per-file optimizer" of the plan)

The plan asked for each file's cheapest path through the storage classes with every fee counted. This is implemented by choosing, for each file, one of the 161 policies above: each policy's cost for each file comes from the validated simulator, so every fee is counted exactly, and the menu contains Intelligent-Tiering itself. A day-by-day dynamic program was set aside: it would need its own fee model, which is the part of the planner the 2022 tests showed to be weak, and it could not include Intelligent-Tiering's internal rules.

For each file, once a year (1 January):

```
score[p] = cost of the file under policy p in the history year
         + mu x reads of the file that waited under p in the history year
         + switch charge, if p is not the policy the file follows now
```

The file moves to the lowest score, unless that score is not lower than its current policy's by more than `margin`. A file with no history stays where it is. In the first year every file starts on the default, Intelligent-Tiering without archive tiers.

* **Settings (21):** menu `online` (only the 30 policies under which no read can wait) with margin 0, 0.1 or 0.25; menu `all` (all 161) with mu in {0, 0.001, 0.01, 0.1, 1, 10} USD per waited read, times margin in {0, 0.1, 0.25}.
* **Switch charge:** an upper bound billed on every file whose policy changes: reading the whole file out at the dearest per-GB price on the sheet (0.03/GB), early deletion at the dearest minimum duration (0.0125/GB), and the dearest single request (0.10 per 1,000). A real switch costs at most this.
* **`chooser` (ours):** the history year is the year before. Causal.
* **`ceiling` (reference, the forecastable ceiling):** the history is the replicate draw of the scored year itself. It knows each file's true expected rate in that year, not the draw it is scored on. Same settings, same switch charge.
* Each file's cost and waits under its chosen policy are summed exactly: files never interact in the simulator. The chooser's cost for a year = sum over files of the chosen policy's cost + switch charges; its waits = the chosen policies' waited reads.

"Ours" for gate R1 = families `seasonal` and `chooser` (112 settings).

## 5. Pick rule and the two waiting rules (D-044)

For each dataset, rolling pair and level (L0: no read waits; L1: at most 1% of reads wait):

1. **Rival pick:** the cheapest rival on the pick year whose share of waited reads meets the level.
2. **Primary rule, `matched`:** ours = the cheapest of ours on the pick year whose waited share is at most min(level, rival pick's share). On the score year: gap = 1 - ours / rival cost; the line passes if the gap is at least the bar **and** ours waited no more than the rival on the score year (as in E1).
3. **Second rule, `equal` (reported, never decides):** ours = the cheapest of ours on the pick year within the level itself. Reported with total waiting hours and the longest wait, for both sides.

The reactive reference and the ceiling are picked by the same rule from their own families.

## 6. Gate R1

* **Condition 1:** on at least two of D1, D3, D4, there is one level at which **both** rolling pairs pass under the matched rule with a gap of **5%** or more.
* **Condition 2:** the same for the ceiling with a gap of **10%** or more.
* **R1 passes if both conditions hold.** If it fails, the build stops and the paper begins (D-038); the deadline does not move.

## 7. Gate R2 (measured on the same runs, decided at the end of stage 5b)

For each matched line: closed = (reactive cost - ours cost) / (reactive cost - ceiling cost), on the score year, when the reactive pick costs more than the ceiling pick. R2 passes if on at least two datasets there is one level at which closed is at least **0.5** in both rolling pairs. Any forecast added in 5b is written down and committed before it is scored, like this protocol.

## 8. Reporting

`python -m sat.experiments.r1 score` writes `reports/r1/table.csv` (every policy and chooser setting, every year), `reports/r1/lines.csv` (every line, both rules, with waiting hours and longest waits) and `reports/r1/verdict.json`. Every line is reported, passing or failing. The per-run CSVs are in `reports/r1/runs/`; the per-file arrays (`data/r1/`) are rebuilt by the run commands and not committed.

## 9. Commands

```
uv run python -m sat.experiments.r1 run --datasets D1 D3 D4 --years 2019 2020 2021 2022 --draw actual --workers 2
uv run python -m sat.experiments.r1 run --datasets D1 D3 D4 --years 2020 2021 2022 --draw replicate --workers 2
uv run python -m sat.experiments.r1 score
```

## 10. Not part of R1

Azure (the zone-redundant price sheet and smart tier, D-041) and Google are not part of this gate. No Azure number is shown before the smart-tier rival exists.
