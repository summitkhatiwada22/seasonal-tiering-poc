# Gate G3 results: the sealed test, 2024 and 2025

**The proof of concept fails by the rules written before the test.** H1 (cost) and H2 (waiting) both fail on the sealed years. By the kill rule in `docs/PREREGISTRATION.md`, the product thesis as stated stops and the paper is written.

* **Where it was close.** The per-file chooser was 52% to 54% cheaper than S3 Intelligent-Tiering on Wikipedia and 39% to 41% on npm, when up to 1% of reads may wait. It failed because in 2024, on both datasets, slightly more of its reads waited than the rival's: 0.277% against 0.245%, and 0.118% against 0.089%.
* **The library data lost** in both years (-15.6% and -12.5%).
* **With no waiting allowed,** nothing of ours beat Intelligent-Tiering.

This repeats the pattern of gate R1 on the rolling years, so it is not an accident of one sample.

## How the test was run

| Item | Record |
| --- | --- |
| Rules | `docs/PREREGISTRATION.md`, in commit cc4b852 |
| Freeze tag | `freeze-g3` on cc4b852, created by the owner on GitHub (release published 2026-10-30 16:32:32 UTC) |
| Why it ran | Gate R1 had failed; the owner overrode the stop rule as a documented deviation (D-051). Nothing was built or tuned after R1 |
| Unlock | The sealed years opened only for code at cc4b852 (`unlock_sealed`: tag on origin = local tag = HEAD, no tracked file changed) |
| Start | 2026-10-30 16:48 UTC, at cc4b852 |
| Sealed files | D1 and D3 views for 2024 and 2025, and the D4 checkouts for 2024 and 2025, from the owner's flash drive. All were written on 2026-10-29, before the tag. Sizes, SHA-256 and times are in `reports/g3/sealed_files.csv` |
| Data preparation after the freeze | The D4 sample for 2024 and 2025 was extracted with the frozen D-030 helpers (`scripts/g3/prepare_sealed.py`). The same code first reproduced the pre-freeze 2023 sample exactly (16,817 rows) |
| Interruption | The container restarted during the ninth scenario (size-low). The last two scenarios were resumed from a checkout of `freeze-g3` (unlocked there). The ten size-low runs finished before the restart were recomputed byte for byte identical. `git diff cc4b852` shows no change to `src/`, `tests/` or `configs/` |
| Scoring | `python -m sat.experiments.g3 score` at the tag. H1 and H2 were also re-derived from the line files with a separate plain-Python script: same answer in all ten scenarios |

## Hypotheses

| ID | Rule (pre-registered) | Result |
| --- | --- | --- |
| H1 Cost | At least 5% cheaper than the best rival under the matched waiting rule, in both sealed years at one level, with the 95% bootstrap interval above zero, on at least 2 of D1, D3, D4 | **Fail**: no dataset passes |
| H2 Wait | At L1, no more cost and at most half the rival's share of waited reads, both years, on at least 2 of 3 | **Fail**: no dataset passes |
| H3 Headroom | Ours' gap over the ceiling's gap (reported) | 0.99 and 0.94 (Wikipedia), 1.99 and 0.76 (npm) |
| H4 Model needed | Ours against the seasonal-naive family alone (reported) | Ours is 9% to 57% cheaper on Wikipedia and npm. The seasonal-naive rule alone is worse than Intelligent-Tiering |
| H5 Robust | The passing hypothesis must hold in 8 of 10 scenarios | **Fail** (no hypothesis passed in base). For the record, H1 held in 2 of 10 scenarios (storage x0.5, fees x1.5) and H2 in 1 (size-low) |
| H6 Net of compute | Compute under 5% of the saving | Measured at 0.01% to 0.13% (1.3% at ten times the assumed price). **Not scored**: the rule counts only datasets that pass H1 or H2, and none did |
| H7 Simulator trust | Gate G2 | Pass (Phase 3) |
| H9 Reproducible | A fresh clone at the tag reproduces every base line to 3 significant figures | **Pass.** A fresh clone of `freeze-g3` re-simulated and re-scored the base scenario from the processed data (2026-10-30, 20:05 to 20:40 UTC). Every rival and ours cost matched within 0.05%; the 11 run files compared during the run were byte for byte identical. Same kind of workspace, not a stranger's machine |

**The PoC passes only if (H1 or H2) and H5, H6, H7 and H9 all pass. It fails.**

## Base lines, matched waiting rule

| Dataset | Pick, then score | Level | Rival pick | Rival cost (USD) | Rival waits | Ours | Ours cost (USD) | Gap | 95% interval | Ours waits | Waits no more | Wait hours (rival / ours) | Longest wait (rival / ours) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Wikipedia (D1) | 2023, then 2024 | L0 | IT | 36.620 | 0.000% | chooser:online:mu0:m0 | 36.620 | +0.0% | +0.0% to +0.0% | 0.000% | yes | 0 / 0 | 0 / 0 h |
| Wikipedia (D1) | 2024, then 2025 | L0 | IT | 36.623 | 0.000% | chooser:online:mu0:m0 | 36.623 | -0.0% | +0.0% to +0.0% | 0.000% | yes | 0 / 0 | 0 / 0 h |
| Wikipedia (D1) | 2023, then 2024 | L1 | IT (archive 90 d, deep 180 d) | 35.874 | 0.245% | chooser:all:mu0.001:m0 | 16.380 | +54.3% | +51.0% to +57.5% | 0.277% | no | 19,740 / 72,554 | 12 / 48 h |
| Wikipedia (D1) | 2024, then 2025 | L1 | IT (archive 90 d, deep 180 d) | 35.793 | 0.260% | chooser:all:mu0.001:m0.1 | 17.028 | +52.4% | +48.6% to +56.0% | 0.221% | yes | 20,731 / 59,755 | 12 / 48 h |
| npm (D3) | 2023, then 2024 | L0 | IT | 0.680 | 0.000% | chooser:all:mu0.01:m0.25 | 0.486 | +28.4% | +14.0% to +47.4% | 0.006% | no | 0 / 36 | 0 / 12 h |
| npm (D3) | 2024, then 2025 | L0 | IT | 0.786 | 0.000% | chooser:online:mu0:m0 | 0.786 | +0.0% | +0.0% to +0.0% | 0.000% | yes | 0 / 0 | 0 / 0 h |
| npm (D3) | 2023, then 2024 | L1 | IT (archive 90 d, deep 180 d) | 0.624 | 0.089% | chooser:all:mu0.001:m0 | 0.381 | +39.0% | +9.1% to +58.8% | 0.118% | no | 381 / 1,632 | 12 / 48 h |
| npm (D3) | 2024, then 2025 | L1 | IT (archive 90 d, deep 180 d) | 0.744 | 0.056% | chooser:all:mu0.001:m0.25 | 0.440 | +40.9% | +20.3% to +59.0% | 0.036% | yes | 269 / 972 | 12 / 48 h |
| Library (D4) | 2023, then 2024 | L0 | IT | 17.651 | 0.000% | chooser:online:mu0:m0 | 17.651 | -0.0% | +0.0% to +0.0% | 0.000% | yes | 0 / 0 | 0 / 0 h |
| Library (D4) | 2024, then 2025 | L0 | IT | 17.183 | 0.000% | chooser:online:mu0:m0 | 17.183 | -0.0% | +0.0% to +0.0% | 0.000% | yes | 0 / 0 | 0 / 0 h |
| Library (D4) | 2023, then 2024 | L1 | IT (archive 90 d, deep 180 d) | 12.530 | 0.351% | seasonal-it-prewarm (archive 90 d, deep 180 d):lead7 | 14.490 | -15.6% | -19.9% to -12.0% | 0.174% | yes | 11,063 / 5,026 | 12 / 12 h |
| Library (D4) | 2024, then 2025 | L1 | IT (archive 90 d, deep 180 d) | 11.962 | 0.327% | seasonal-it-prewarm (archive 90 d, deep 180 d):lead7 | 13.456 | -12.5% | -16.8% to -9.0% | 0.197% | yes | 10,236 / 5,850 | 12 / 12 h |

## Base lines, equal 1% allowance (reported only)

| Dataset | Pick, then score | Ours | Gap | Waits (rival / ours) | Wait hours (rival / ours) | Longest wait (rival / ours) |
| --- | --- | --- | --- | --- | --- | --- |
| Wikipedia (D1) | 2023, then 2024 | chooser:all:mu0.001:m0 | +54.3% | 0.245% / 0.277% | 19,740 / 72,554 | 12 / 48 h |
| Wikipedia (D1) | 2024, then 2025 | chooser:all:mu0.001:m0 | +52.7% | 0.260% / 0.242% | 20,731 / 64,373 | 12 / 48 h |
| npm (D3) | 2023, then 2024 | seasonal:deep_archive+copies:lead30:recent30:bulk | +20.9% | 0.089% / 0.447% | 381 / 2,916 | 12 / 48 h |
| npm (D3) | 2024, then 2025 | chooser:all:mu0.001:m0 | +49.3% | 0.056% / 0.082% | 269 / 2,112 | 12 / 48 h |
| Library (D4) | 2023, then 2024 | seasonal:deep_archive+copies:lead30:recent30:bulk | -0.6% | 0.351% / 0.629% | 11,063 / 32,316 | 12 / 48 h |
| Library (D4) | 2024, then 2025 | seasonal:deep_archive+copies:lead30:recent30:bulk | -5.3% | 0.327% / 0.923% | 10,236 / 47,592 | 12 / 48 h |

## H5: the scenarios

| Scenario | H1 (D1 / D3 / D4) | H1 holds | H2 (D1 / D3 / D4) | H2 holds |
| --- | --- | --- | --- | --- |
| base | no / no / no | no | no / no / no | no |
| storage-x0.5 | yes / yes / no | yes | no / yes / no | no |
| storage-x1.5 | no / no / no | no | no / no / no | no |
| fees-x0.5 | no / no / no | no | no / no / no | no |
| fees-x1.5 | yes / yes / no | yes | no / no / no | no |
| restore-low | no / no / no | no | no / no / no | no |
| reads-low | no / no / no | no | no / no / no | no |
| reads-high | no / no / no | no | no / no / no | no |
| size-low | no / no / no | no | yes / yes / no | yes |
| size-high | no / no / no | no | no / no / no | no |

## H3, H4, H6 (base)

| Line | H3 ours gap / ceiling gap |
| --- | --- |
| D1_2024 | 0.99 |
| D1_2025 | 0.94 |
| D3_2024 | 1.99 |
| D3_2025 | 0.76 |

| Line | H4 ours against the seasonal-naive family alone |
| --- | --- |
| D1_2024_L0 | +14.6% |
| D1_2024_L1 | +57.0% |
| D1_2025_L0 | +14.3% |
| D1_2025_L1 | +55.2% |
| D3_2024_L0 | +37.5% |
| D3_2024_L1 | +46.7% |
| D3_2025_L0 | +9.1% |
| D3_2025_L1 | +41.3% |
| D4_2024_L0 | +22.6% |
| D4_2024_L1 | +0.0% |
| D4_2025_L0 | +21.2% |
| D4_2025_L1 | +0.0% |

| Line | Core-hours | Saved (USD) | Compute / saving at 0.04 USD per core-hour | at 0.40 |
| --- | --- | --- | --- | --- |
| D1_2024 | 0.063 | 19.49 | 0.013% | 0.129% |
| D1_2025 | 0.066 | 18.76 | 0.014% | 0.141% |
| D3_2024 | 0.008 | 0.24 | 0.131% | 1.315% |
| D3_2025 | 0.008 | 0.30 | 0.111% | 1.112% |
| D4_2024 | 0.059 | -1.96 | n/a | n/a |
| D4_2025 | 0.059 | -1.49 | n/a | n/a |

## Azure ZRS (reported): the chooser against smart tier

| Dataset | Pick year | Ours | Gap |
| --- | --- | --- | --- |
| Wikipedia (D1) | 2023 | chooser:all:mu0:m0.1 | +0.02% |
| Wikipedia (D1) | 2024 | chooser:all:mu0:m0.1 | +0.03% |
| npm (D3) | 2023 | chooser:all:mu0:m0 | +0.10% |
| npm (D3) | 2024 | chooser:all:mu0:m0 | +0.08% |
| Library (D4) | 2023 | chooser:all:mu0:m0.25 | +0.06% |
| Library (D4) | 2024 | chooser:all:mu0:m0.1 | +0.09% |


## What it means

* **Seasonal forecasting on its own is not the lever.** The seasonal-naive family, picked by the same rule, cost 0.6% to 29% more than the rival on all twelve base lines.
* **The saving is real, but it is bought with waiting.** Choosing a policy per file saves 39% to 54% of the bill on Wikipedia and npm at L1. It does so by leaving some large, rarely read files in deep archive, where a read waits for a bulk restore (up to 48 hours, against the rival's 12). The share of reads that wait is similar to the rival's. The total waiting hours are 2.9 to 4.3 times the rival's.
* **The method cannot hold its waits at the rival's level every year.** It sets its waiting allowance from last year's waits, and in 2024 it overshot on both datasets, by about 0.03 percentage points. In R1 the same thing happened once (0.224% against 0.218% on Wikipedia). In two scenarios, storage at half price and fees at 1.5 times, the pick waited less and H1 held. In the others it did not. That fragility is the main finding. It is also why H5 would have failed even if base had passed. The forecastable ceiling, which knows each file's true read rate (not the draw that is scored), waited no more than the rival on all four Wikipedia and npm lines at L1, while 20% to 56% cheaper; it did the same on all four in R1. So the per-file economics hold; what fails is predicting next year's reads from last year's.
* **Library data does not repeat from year to year.** On D4 the chooser cost 12% to 29% more than Intelligent-Tiering with archive tiers in every year from 2023 to 2025. The cheapest of ours that met the waiting rule on the pick year was a seasonal policy (Intelligent-Tiering with forecast restores), and it lost by 12.5% and 15.6%. The library has now lost in all four rolling years tested (R1 and G3). Even the ceiling never saved 5% there (+4.9% to -15.1% across R1 and G3).
* **On Azure there is nothing to win.** With no archive tier on the zone-redundant sheet, the chooser ties smart tier (+0.02% to +0.10%). Google was not tested in round two.

## Kill and pivot rules applied

* **H1 and H2 both fail.** The product thesis "forecasting beats reactive auto-tiering" stops; the paper is written.
* **Only-H2 pivot (a latency product) does not apply.** H2 failed: ours does not cut waiting at no extra cost; it trades waiting for money.
* **Paper or advisory work.** What survives is a fee-accurate simulator and per-file cost analysis that show where a waiting budget is worth money. That could be an advisory tool, not an automated tiering product. It is a direction for the paper, not a result of this test.

Every number above comes from `reports/g3/`: `results.json`, `<scenario>/lines.csv`, `<scenario>/table.csv` and the per-run CSVs. Tables generated by `scripts/g3/tables.py`.
