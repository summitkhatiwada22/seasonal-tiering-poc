# Phase 5 report: stage 5a and gate R1 (2026-10-30)

**Gate R1 failed by the rule written before the run, narrowly.** By that rule (D-038), the build stops: stage 5b's forecasts were not built and the next step is the paper, unless the owner decides otherwise (see "What happens next"). The protocol is `docs/R1_PROTOCOL.md`. It was committed and pushed (0bde4de) before any real-data run of these methods. The Azure addendum was committed in 9b13438, before its own runs.

The per-file chooser (the plan's exact per-file optimizer) is much cheaper than S3 Intelligent-Tiering on Wikipedia and npm when up to 1% of reads may wait: 28% to 48% on Wikipedia and 40% to 43% on npm, on years its settings did not see. On npm it passes both rolling years. On Wikipedia it passes one year and misses the other because 0.224% of reads waited against the rival's 0.218%. On the library data it loses, after the 2020 pandemic year broke the "last year predicts next year" assumption. With no waiting allowed, nothing beats Intelligent-Tiering anywhere.

## Gate R1

AWS, central setting, matched waiting rule (ours may wait no more than the rival picked on the pick year). Gap = how much cheaper than the rival pick, scored on the score year. "Waits" = share of reads that waited. L1 means up to 1% of reads may wait.

| Dataset | Pick, then score | Rival pick (L1) | Rival waits | Ours (picked on the pick year) | Gap | Ours waits | Line passes | Ceiling gap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Wikipedia (D1) | 2020, then 2021 | IT, archive 90 d, deep 180 d | 0.218% | chooser, mu 0.001, margin 0.25 | +48.5% | 0.224% | **no** (waits) | +51.4% |
| Wikipedia (D1) | 2021, then 2022 | same | 0.245% | chooser, mu 0.01, margin 0 | +27.6% | 0.097% | yes | +55.2% |
| npm (D3) | 2020, then 2021 | same | 0.218% | chooser, mu 0.001, margin 0 | +40.4% | 0.071% | yes | +44.5% |
| npm (D3) | 2021, then 2022 | same | 0.153% | chooser, mu 0.001, margin 0 | +43.4% | 0.072% | yes | +50.9% |
| Library (D4) | 2020, then 2021 | same | 0.259% | chooser, mu 0.001, margin 0.25 | -37.0% | 0.772% | no | -3.3% |
| Library (D4) | 2021, then 2022 | same | 0.191% | IT with forecast restores, lead 7 | -16.4% | 0.116% | no | +4.9% |

At no waiting (L0), the best of ours costs the same as plain Intelligent-Tiering on every line (gap 0.0%): in effect the online chooser keeps every file there. One exception: on npm 2020-2021 the L0 pick waited 0.024% in the score year and failed.

| Condition | Rule | Result |
| --- | --- | --- |
| 1. A method of ours, 5% or more, both rolling years, on two of D1, D3, D4 | matched waiting | **Holds on D3 only. Fails** |
| 2. The forecastable ceiling, 10% or more, same way | matched waiting | Holds on D1 and D3. Passes |
| **R1** | both conditions | **Fails** |

`reports/r1/verdict.json`, every line in `reports/r1/lines.csv`, every policy and chooser setting in `reports/r1/table.csv`.

## What the results say

1. **The win is spending the waiting allowance where it saves the most.** In the 2022 Wikipedia choice (mu 0.001, margin 0), 275 of 9,370 files hold 55% of the bytes. They go to fixed archive-class lifecycle rules: big files, rarely read, whose occasional read waits. Another 836 files (19% of bytes) go to archive storage with restored copies. The other 8,239 stay on Intelligent-Tiering. This is per-file economics, not seasonality.
2. **Waiting hours rise even when the share of waited reads does not.** Under the matched rule ours waited fewer or about as many reads, but longer: Wikipedia 2022 21,573 hours against 19,445; npm 444 and 828 hours against 356 and 392. The longest wait is 48 hours (bulk restores) against 12. D-044's second rule reports exactly this.
3. **With an equal 1% allowance**, ours saves 50% and 52% on Wikipedia but waits 3.9 to 4.5 times as many hours (78,308 against 17,215; 75,024 against 19,445).
4. **The library data fails for a reason that matters.** In the D4 sample, physical checkouts fell from 46,079 in 2019 to 12,626 in 2020 and recovered only to 21,932 in 2021 (digital rose throughout), so 2020 is a poor guide to 2021. The chooser on 2020's history waited 3 times as much as the rival and cost 37% more. Even the ceiling, which knows 2021's true rates, gains nothing at the rival's waiting there. A year-on-year selector is exposed to regime changes. The plan's Phase 7 named 2020 as a stress test; it arrived early.
5. **The forecastable ceiling is close.** The causal chooser closes 66% to 96% of the gap between the reactive reference and the ceiling on Wikipedia and npm at L1. Knowing true rates would add little; last year's per-file outcome already carries most of it.
6. **Azure: smart tier beats every fixed policy.** On the zone-redundant sheet (addendum A), smart tier costs 35.9 against 43.5 for the best seasonal policy on Wikipedia 2021. The other figures: npm 0.457 against 0.472, library 18.7 against 27.0. The best other rival is 27% to 82% dearer than smart tier. The chooser ties smart tier (0.0% to 0.2% cheaper). The Phase 4 Azure "wins" (+9% to +26%) were against a weak rival, as D-041 suspected (`reports/r1/zrs/`).

## Gate R2 (measured, not decided)

R2 passes by the letter on all three datasets, but it is moot: R1 failed, so no forecast was built in 5b. The letter is also weaker than it looks. At L0 every line scores "closed = 1.0", because ours and the ceiling both equal the rival while the reactive reference is worse. That is a flaw in the pre-registered definition, recorded here. At L1 the honest numbers are in point 5 above.

## Stage 5a items

| Item | Status |
| --- | --- |
| Waiting rule written first (D-044) | Done; in the protocol |
| Planner prices bulk restores; lead time matches 12 h and 48 h | Done (`Planner.speed`, `TwoTier.speed`; leads 7 and 30 days) |
| Exact per-file optimizer | Done as the per-file chooser (D-045); 21 settings |
| Forecastable ceiling | Done (replicate draw from the true rates) |
| Zone-redundant Azure sheet and smart tier | Done (D-049), official prices in `docs/evidence/official-prices-azure-zrs-2026-10-30.md` |
| Rolling-year scoring with both waiting rules and waiting hours | Done; per-file wait hours added to the simulator |

## Stage 5b items

| Item | Status |
| --- | --- |
| Rate and trend forecasts, robustness layer, calendar features | **Not built**: R1 failed (D-038) |
| Wikimedia Commons dataset | Not started (would follow from 5b) |
| Compression sizing test (approved, D-047) | **Done**, below. A measurement, not part of the build |
| Compute cost of the method (H6) | Measured, below |
| Leakage audit | Done, below |

### Compression sizing test (real npm tarballs)

1,135 tarballs of 193 D3 packages (latest version and up to five earlier ones), 108 MB as published, 415 MB unpacked. Every codec round-tripped byte for byte (SHA-256). The tarballs were deleted after measuring. Results: `reports/compression/npm_sizing.json` and `npm_sizing_packages.csv`. Script: `scripts/compression/npm_sizing.py`.

| Method | Size against the published .tgz |
| --- | --- |
| gzip -9 of the same tar | 99.1% |
| zstd -3 | 87.1% |
| zstd -19 | 70.8% |
| xz -9 | 66.6% |
| All versions of a package in one stream, zstd -19 long window | 23.8% |
| All versions of a package in one stream, xz -9 | 21.4% |
| zstd -19 with a trained 110 KB dictionary (other half of packages) | 100.9% of zstd -19 alone: no gain |

* 21.8% of the bytes of files inside the tarballs repeat an earlier file exactly (whole-file dedup across versions and packages).
* The median published tarball is 8.2 KB and 90% are under 128 KB. On AWS such objects never leave Standard and Intelligent-Tiering does not tier them. For a package archive, keeping versions together, which saves about 76% to 79% of bytes, matters far more than tiering.
* Speeds (MB/s of tar, one thread, measured while simulations used both cores, so low): zstd -3 223 compress and 799 decompress; zstd -19 2.8 and 723; xz -9 2.3 and 73; gzip -9 22 and 486.

### Compute cost (H6)

Simulating all 161 policies for one dataset-year took 384 to 409 seconds for Wikipedia (9,370 files), 232 to 248 for the library (10,000) and 29 for npm (270), on one core. Each annual choice needs one such run. At an assumed USD 0.04 per core-hour, that is about USD 0.005 a year for Wikipedia, against savings of USD 10 to 17 a year at these scales: under 0.1%. H6's bar is under 5%.

### Leakage audit

The chooser's inputs for year Y are the simulated per-file costs and waits of year Y-1 (warm-up Y-2), the file sizes and its own choice for Y-1. A test (`test_chooser_history_is_the_year_before`) and a planted bug ("chooser sees the scored year") check this. The ceiling alone reads the scored year, and only from an independent draw; a planted bug ("ceiling chooses on the scored draw") checks that. Reads are cut at the end of the measured year ("rolling year sees the next year"). No file from 2023 or later was opened.

## Limits

* All three datasets map demand to reads by assumption (D-031): about 18 reads a year for the median file, with sizes drawn from one object-store trace (D-032). Real access logs could differ in both.
* The switch charge is a deliberate upper bound. A real chooser would switch more cheaply and so do a little better.
* Two rolling pairs and three datasets make a small sample. The sealed years have not been opened.
* The waiting rule counts waited reads, not hours. Ours keeps that count at or below the rival's while making some reads wait up to 48 hours.

## What happens next

By D-038 the build has stopped and the paper begins. Two choices are the owner's:

1. **Write the paper now (the rule's default).** The story is a fee-accurate benchmark with three findings. First, managed tiering beats seasonal forecasting. Second, per-file choice of policy saves 28% to 48% on two of three datasets if some reads may wait 48 hours. Third, a pandemic-like shift breaks it.
2. **Override R1 as a documented deviation, freeze the chooser as it is (no further building) and run the sealed test once (G3).** The sealed years are untouched, so G3 would still be a clean confirmatory test of a method fixed today. It needs the freeze tag created by the owner on GitHub. My view: this is worth doing, because R1 failed on a 0.006-point waiting difference on one line. But it is a deviation from a rule the owner approved, and must be labelled as one.
