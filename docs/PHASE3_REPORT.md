# Phase 3 report: cost and waiting-time simulator

Date: 2026-10-30. Verdict: **Gate G2 PASSED.** The simulator matches every hand calculation (24 of 24, relative error under 1e-9) and the owner's AWS Pricing Calculator readings (4 of 4, to the cent). Its tests catch 22 of 22 deliberately planted bugs.

No real data was used in this phase, and the sealed test years (2024-2025) were not touched.

## What was built

`src/sat/sim/` turns a storage plan into a bill and a list of waits, for AWS, Google and Azure.

- **Inputs:**
  - the stored objects (sizes, how many of each, the day each one is created);
  - daily reads per object;
  - a plan: the class each object is in on each day, plus "warm it up early" restores (day, how long to keep the copy, speed).
- **Bill:** ten categories:
  - storage;
  - archive overhead;
  - temporary copies;
  - early deletion (leaving a class before its minimum time);
  - moving between classes;
  - retrieval fees;
  - restore requests;
  - read requests;
  - uploads;
  - the rivals' monitoring fees.

  Egress is off by default. The bill is broken down by day and by object.
- **Waits:**
  - reads that found their object still frozen;
  - wait hours, counting every read (upper bound) and counting only the first read each day (lower bound);
  - the longest wait and wait percentiles.

  Each is reported at both the high and low end of the provider's stated restore time.
- **The rivals' billing:** S3 Intelligent-Tiering (optional archive tiers included) and Google Autoclass (Nearline or Archive terminal class). Their tier moves follow the providers' published day counts. In Phase 4 they become baselines.
- **Billing rules** are in `docs/SIM_RULES.md`: 27 rules, each quoted from an official AWS, Google or Microsoft page read on 2026-10-30, plus 10 written assumptions where the pages say nothing. Each assumption states which way any error leans.
- **`make simulate`** runs a smoke test on the synthetic data.

## Gate G2 evidence

| Check | What | Result |
| --- | --- | --- |
| Hand calculations | 24 cases in `docs/HAND_CALCS.md`, held as literal numbers in `tests/test_sim_hand.py`. Includes Microsoft's own worked rehydration example ($26.0005004) and Google's own lifecycle/rewrite example | 24 / 24 match (relative error < 1e-9) |
| AWS Pricing Calculator | The owner's four readings, run through the simulator as a 31-day month: Glacier Flexible $46.18, Deep Archive $120.32, Standard $230.70 (with the calculator's S3 Select line), Glacier Instant $70.00 | 4 / 4 match to the cent |
| Properties | Random plans on all three clouds: <ul><li>totals are consistent and never negative;</li><li>more reads never cost less;</li><li>pre-warming in time removes every wait;</li><li>the low restore time never waits longer than the high one;</li><li>Google never waits;</li><li>an all-hot plan equals the closed-form formula;</li><li>N identical objects equal one object weighted N;</li><li>results are deterministic;</li><li>bad input is refused.</li></ul> | all pass (32 test cases) |
| Check of the checks | `scripts/mutation_check.py` plants 22 realistic bugs one at a time, for example: <ul><li>decimal instead of binary GB;</li><li>the wrong early-deletion basis;</li><li>Google lifecycle resetting the clock;</li><li>the copy expiry not rounded to midnight;</li><li>storage billed before an object exists.</li></ul> | 22 / 22 caught. The first run caught 16 of 19, and the three misses became hand calculations H19 to H21 |
| Speed | `scripts/bench_sim.py`: 10,000 objects x 3,653 days (D1's real size) with random plans and about 40,000 restores, on the 2-CPU build machine | 2.4 to 5.0 s per run on every cloud and rival |

`make check`: 162 tests pass; lint and strict type checks are clean.

## Findings worth knowing

1. **Three settings in the provider rules decide many results:**
   - **Google:** lifecycle moves keep the object's age clock and never pay early deletion, while a rewrite (needed to move *up*) pays both retrieval and early deletion.
   - **AWS:** a restored copy lives until the next midnight after the number of days asked for, and the archived object is billed at the same time.
   - **Azure:** it uses 30-day months for early deletion but calendar months for storage, in Microsoft's own example.
2. **Two price-sheet gaps closed (D-026):** Azure archived blobs carry 8 KB of metadata each, billed at a cooler tier's rate (earlier listed as "none"). AWS and Intelligent-Tiering restore ranges now have their lower ends.
3. **Smoke test on synthetic data (10,000 objects, 3 years, trivial plans, not a result):**
   - Everything in the coldest class costs 9 to 44 times more than everything hot, because every read pays retrieval and restore fees. Sixty percent of reads wait on AWS and Azure.
   - Intelligent-Tiering and Autoclass come in about 11-19% below all-hot.

   So the bar for a forecasting plan is the rivals, not the trivial extremes.

## Limits (what the simulator does not model)

- **Time of day:** reads are assumed at 00:00. Waits are overstated, never understated, for every plan alike (assumption A1).
- **Provider throughput limits:**
  - Azure caps high-priority rehydration at 10 GiB per hour per account and warns that bulk rehydration "do[es] not scale linearly".
  - AWS expedited restores need provisioned capacity under load.

  Plans that restore many objects at once may be optimistic. Phase 7 (robustness) should test restore volume.
- **Not modelled:**
  - volume price tiers (only the first 50 TB of S3 Standard);
  - the free tier;
  - multi-region storage;
  - Azure smart tier (no LRS price);
  - Google soft delete (assumed off, assumption A7; re-run with 7 days in Phase 7).
- **Policy rules not enforced by the simulator:** the AWS lifecycle waterfall, the default that objects under 128 KB do not transition, and the AWS lifecycle rule on minimum days in Standard before Standard-IA. Phase 4 policies must respect them, and Phase 4 adds a check.
- **Memory:** the read table is held in full (objects x days). D1 at 10,000 x 3,653 is fine. The synthetic L scale (1 million objects) needs chunking. That is exact, because objects do not interact, and it is a Phase 4 task.

## Independence

The hand calculations were written before the code, from the official pages, and two of them are the providers' own published examples. They were written by the same author as the code (Claude), so they are not a fully independent check. A separate reviewer could re-derive a sample of cases from `docs/SIM_RULES.md` alone.

## Next: Phase 4

Build the baseline policies:
- all Standard;
- lifecycle rules;
- Intelligent-Tiering and Autoclass, with a warm-up period;
- an oracle;
- the seasonal-naive policy.

Phase 4 also adds the sealed-year loader guard, size assignment (D-009) and the mapping from page views and downloads to object reads. Early check E1 follows on the 2023 validation year.
