# Phase 4 report: baseline policies, seasonal-naive, early check E1

Date: 2026-10-30. Rules: [E1_PROTOCOL.md](E1_PROTOCOL.md). Policies: [POLICIES.md](POLICIES.md).

## Verdict

**By the rule fixed before the data was read: CONTINUE.** All three real datasets have a passing line.

**But the signal is narrow and weak, and the owner should weigh it before Phase 5:**

1. **Every pass is on Azure.** On Azure LRS, Microsoft offers no automatic tiering, so the best rival is "keep everything hot" or Azure's last-access rules.

   Against the rivals this project set out to beat, S3 Intelligent-Tiering on AWS and Autoclass on Google, seasonal-naive **never passes**: it loses on every dataset, or is within half a percent (npm on Google +0.4%, npm on AWS -0.0%), down to -69%.
2. **Two of the three Azure passes rest on flagged series.** These are the bursty or very thin series marked from pre-2023 data (D-019). Without them the saving is **4.2% on Wikipedia and 4.5% on npm**, both under the 5% bar.
3. **The third Azure pass is not seasonality.** On the library data, our reactive copy, which ignores last year, is 5.2% cheaper than the seasonal policy.
4. **On synthetic data with planted seasons (D7), ours loses on every cloud,** by about as much as on the no-season control. The simple policy does not turn a known season into savings.

What E1 shows is where a forecast could still pay:
- **On AWS,** a perfect forecast beats Intelligent-Tiering by 4-27% at no waiting. Seasonal-naive captures none of it.
- **On Google,** even a perfect forecast barely moves against Autoclass (-7% to +6%).
- **On AWS, at the 1% waiting level,** Intelligent-Tiering plus forecast restores roughly **halves the share of reads that wait**, for 1-19% more cost.

## How E1 was run

The order is checkable in git:

| Step | Commit |
| --- | --- |
| Policies, data rules and the E1 protocol, before any real-data run | `652911d` |
| 2022 picks for every dataset, cloud and waiting level, before any 2023 run | `d1cf04d` |
| 2023 result, scored once | `3db925d` |

Data and settings:
- **Tuning:** 2021-2022 simulated, 2022 measured, with data up to 2022 only.
- **Validation:** 2022-2023 simulated, 2023 measured.
- **Sealed years:** 2024 and later are refused by folder name and were never opened (D-029).
- **Central setting:** IBM-trace file sizes; the median object is read about 18 times a year; upper-end restore times.

Selection:
- **Rivals:** the cheapest rival setting meeting the waiting level.
- **Ours:** the cheapest seasonal setting waiting no more than that rival.
- **Pass:** at least 5% cheaper on 2023, with no more waiting than the rival.

## Results (central, 2023)

Costs are the 2023 bill in USD. **Gap** = 1 - ours / rival, so positive means ours is cheaper.

"No waiting" (L0) is shown. At "at most 1% wait" (L1), the Azure and Google picks are the same; the AWS rows are below.

| Dataset | Cloud | Best rival (2022 pick) | Rival | Ours | Gap | Ours vs reactive | Perfect forecast | Pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D1 Wikipedia | AWS | Intelligent-Tiering | 36.60 | 42.81 | -16.9% | +2.7% | +4.3% | no |
| D1 Wikipedia | Google | Autoclass (Archive) | 31.41 | 36.63 | -16.6% | +2.2% | -2.5% | no |
| D1 Wikipedia | Azure | all hot | 38.63 | 35.13 | **+9.1%** | +7.3% | +19.9% | **yes** |
| D3 npm | AWS | Intelligent-Tiering | 0.638 | 0.638 | -0.0% | +2.0% | +12.7% | no |
| D3 npm | Google | Autoclass (Archive) | 0.551 | 0.548 | +0.4% | -0.5% | +6.0% | no |
| D3 npm | Azure | all hot | 0.699 | 0.537 | **+23.1%** | +12.0% | +29.4% | **yes** |
| D4 library | AWS | Intelligent-Tiering | 19.04 | 25.83 | -35.7% | -6.6% | +26.8% | no |
| D4 library | Google | Autoclass (Archive) | 13.34 | 22.54 | -69.0% | -6.6% | -7.3% | no |
| D4 library | Azure | last access, cool after 30 days | 29.92 | 22.10 | **+26.1%** | -5.2% | +52.8% | **yes** |

On AWS at L1 (at most 1% of reads wait), the rival is Intelligent-Tiering with Archive Access after 90 days and Deep Archive Access after 180. Ours is the same service plus forecast restores 7 days ahead:

| Dataset | Rival cost | Ours | Gap | Reads that waited: rival / ours | Waiting hours: rival / ours |
| --- | --- | --- | --- | --- | --- |
| D1 | 35.87 | 37.82 | -5.4% | 0.24% / 0.13% | 18,424 / 8,953 |
| D3 | 0.620 | 0.627 | -1.1% | 0.11% / 0.09% | 353 / 290 |
| D4 | 14.17 | 16.93 | -19.4% | 0.26% / 0.15% | 12,231 / 6,594 |

The policies picked as ours were:
- The fee-aware planner (D1 and D3).
- The warm/cold rule (D4: AWS, Google and Azure).
- Intelligent-Tiering with forecast restores (AWS at L1).

The full picks are in `reports/e1/central/picks.json`, and every 2022 and 2023 run is in `tune_results.csv` and `eval_results.csv`.

### Groups (Azure, L0)

| Dataset | Group | Objects | Gap |
| --- | --- | --- | --- |
| D1 | cohort A (most viewed) | 5,000 | +9.0% |
| D1 | cohort B (random) | 4,518 | +9.2% |
| D1 | flagged (bursty or thin) | 1,563 | +30.9% |
| D1 | not flagged | 7,955 | **+4.2%** |
| D3 | flagged | 36 | +70.6% |
| D3 | not flagged | 251 | **+4.5%** |
| D4 | physical | 5,117 | +21.2% |
| D4 | digital | 4,883 | +32.6% |

Objects that do not exist by the end of 2023 are not counted, so group sizes can be below the list size.

### Synthetic check (D7 planted seasons, D7-control none)

| Cloud and level | D7 gap | D7-control gap | D7 ours vs reactive | D7-control ours vs reactive |
| --- | --- | --- | --- | --- |
| AWS L0 | -23.1% | -19.2% | -1.0% | +0.6% |
| AWS L1 | -5.5% | -5.2% | +9.8% | +6.5% |
| Google | -19.7% | -16.4% | +1.6% | +0.6% |
| Azure | -6.1% | -6.7% | -1.9% | -1.9% |

The protocol expected a gain on D7. There is none. Ours does not pass on the control either, so there is no false win to explain, but the pipeline check "D7 should show a gain" **failed**. Seasonal-naive with these mechanisms does not exploit even a planted season well enough to beat the rivals.

### Ceilings

| Ceiling | What it shows |
| --- | --- |
| **Perfect forecast** | The best `oracle` setting, our policy fed the true 2023 reads, against the rival at the same waiting. This is the ceiling for *this kind of policy with a better forecast* |
| **Hindsight bound** | Picks the cheapest of all plans run, object by object, knowing 2023: 4.5-15% on Google, 31-62% on AWS and Azure (`verdict.json`). It is not specific to seasonality: it is just as large on the no-season control (AWS 46%), because it mostly rewards knowing which objects are read at all. It is an upper reference, not a target |

## Sensitivities

Each line is the 2023 gap of ours against the best rival at "no waiting" (L0). **Bold** = passes. The sensitivity settings tuned their own picks on 2022 (committed in `5ea6bd0` before their 2023 runs). Seeds 2 and 3 and fast restores reuse the central picks.

| Setting | D1 AWS | D1 Google | D1 Azure | D3 AWS | D3 Google | D3 Azure | D4 AWS | D4 Google | D4 Azure | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| central | -16.9% | -16.6% | **+9.1%** | -0.0% | +0.4% | **+23.1%** | -35.7% | -69.0% | **+26.1%** | continue |
| reads-low (about 2 reads a year) | -11.8% | -14.4% | +4.5% | +4.4% | -6.5% | **+40.7%** | -24.8% | -38.8% | **+19.0%** | continue |
| reads-high (about 180 a year) | -4.0% | -4.3% | -0.9% | +4.7% | +4.1% | **+13.4%** | -47.1% | -73.7% | **+23.4%** | continue |
| size-low (median about 25 KB) | -1.4% | -0.7% | -14.7% | +0.0% | -0.6% | -38.1% | -4.5% | -8.4% | **+13.3%** | continue |
| size-high (median about 17 MB) | -17.3% | -16.6% | **+9.3%** | -5.7% | -6.7% | **+16.6%** | -35.5% | -70.4% | **+27.4%** | continue |
| restore-low (fast restores) | -16.9% | -16.6% | **+9.1%** | -0.0% | +0.4% | **+23.1%** | -35.7% | -69.0% | **+26.1%** | continue |
| seed-2 (another draw of reads) | -17.3% | -16.6% | **+9.5%** | -0.1% | -0.9% | **+24.3%** | -36.5% | -69.7% | **+25.7%** | continue |
| seed-3 | -15.0% | -14.7% | **+9.8%** | +0.9% | -1.2% | **+21.5%** | -36.4% | -69.6% | **+25.8%** | continue |

What it says:

- **No setting makes ours pass on AWS or Google.** The closest is npm on AWS at about +4.5% when files are read rarely or often, still under the bar.
- **The Azure passes hold across read draws and restore times** (not fragile). They depend on file size: with small files (size-low), fees per request and per GB dominate, and Wikipedia and npm turn into clear losses on Azure.
- **Wikipedia on Azure passes only at the central and high-size settings.** At low and high read levels it falls to +4.5% and -0.9%.
- At the 1% waiting level the picture is the same; every line is in `reports/e1/<setting>/verdict.json`.

## Checks

| Check | Result |
| --- | --- |
| Tests | 253 (91 new in Phase 4), all passing locally and on GitHub |
| Future-leak tests | Every policy that can be run in practice, ours and the rivals, is tested so that changing reads on or after a day never changes its plan before that day. The seasonal forecast can look back 364 days at most and refuses to look at today |
| Sealed years | 2024+ refused by folder name before opening (tested). Read scaling uses 2016-2022 only (tested). A year's reads are identical whether the table stops at 2022 or 2023 (tested) |
| Planted bugs | 36 of 36 caught (22 in the simulator from Phase 3, 14 new in the data, policy and E1 code). The first run caught 32: four tests were too weak (the code was right in each case) and were tightened. The check now runs in a separate copy of the repository, because it edits source files |
| AWS rule check | Every AWS plan is checked: objects under 128 KB never leave Standard; class order is the lifecycle waterfall; no restore of an object that was never archived |
| Rival menu | Widened before any real-data run: 15 rival settings on AWS, 9 on Google, 12 on Azure (D-033) |

## Limits

- **Azure smart tier is missing.** Azure's own automatic tiering exists only for zone-redundant storage, which has no price on our LRS sheet. Every pass is on Azure LRS. A customer on ZRS would have a managed rival this test does not include.
- **No object sizes in the real data.** The same object sizes are drawn for every plan (D-032).
- **Reads are scaled page views, downloads and checkouts (D-031).** The central level is a stated guess.
- **D4 is monthly.** The library data's monthly totals are spread over each month, so within-month timing is unknown.
- **Waiting time is coarse.** Reads arrive at midnight (A1), so waits are overstated equally for all plans.
- **The planner is a heuristic.** Its perfect-forecast version is not always better than its seasonal version, so the planner leaves money on the table. The perfect-forecast ceiling above is "the best of our policies with true reads", not the best possible policy.
- **Observation costs are an assumption** (A12, access logs). They are small, but they are charged only to our policies.
- **The per-object arrays behind the bound are not in git.** The hindsight bound uses per-object arrays that are regenerated by the run. They were committed once by mistake in `d1cf04d` (79 MB, numbers only) and removed in `9c00861`. Removing them from history would need a force push, left to the owner.

## Process notes

- **The run was interrupted once.** The first attempt at Phase 4 hit the session usage limit midway and the workspace restarted. The work on disk was checked file by file against the session log, the full test suite was re-run, and the work continued from there. Nothing was lost except a partial synthetic run, which was re-run.
- **One protocol clarification was made before any 2023 run.** Sensitivity runs on 2023 score the picks only; the hindsight bound is a central-setting line. It is in the picks commit.

## Recommendation

The rule says continue, and the rule stands. The narrow reading above suggests Phase 5 should be scoped to the two places where room exists, with a stop rule of its own:

1. **AWS: a better forecast against Intelligent-Tiering.** The perfect forecast shows 4-27% of room at no waiting, and seasonal-naive takes none of it. Phase 5's forecast has to close a real part of that gap on 2023 to be worth anything.
2. **Azure: whether seasonality beats a fee-aware reactive policy on unflagged data.** Today it is +4% over the rival and mixed against reacting.

Google is not worth pursuing: Autoclass is within a few percent of a perfect forecast. The waiting-time benefit on AWS is real but small, and could be reported as a secondary result.

Writing up E1 as it stands is also a defensible choice. The owner decides.

## Addendum, 2026-10-30: the "oracle is never beaten" check (audit before round two)

The plan's Phase 4 list asked to check that the oracle is never beaten. From `reports/e1/central/*_results.csv`:

* **At no waiting (L0) it holds everywhere:** on every dataset and cloud, in 2022 and 2023, the cheapest oracle setting costs no more than the cheapest seasonal one.
* **At up to 1% waiting (L1) it fails on AWS for D3 and for the synthetic control:** for example D3 in 2023, `seasonal:deep_archive+copies:lead30:recent90` costs 0.423 USD (0.30% of reads wait) against the best oracle at 0.558 USD (no waits). The oracle references were built with lead 1 and recency 0, the shapes that never wait. They are a ceiling for this policy shape with a perfect forecast, not for the waiting-tolerant settings (restored copies kept 30 or 90 days) that the seasonal grid also contains.

Consequence: the "Perfect forecast" column above understates the room at L1 on AWS. It was a reference only, so the E1 verdict does not change. Round two replaces the oracle with the forecastable ceiling, which chooses from the same menu as ours (docs/R1_PROTOCOL.md).
