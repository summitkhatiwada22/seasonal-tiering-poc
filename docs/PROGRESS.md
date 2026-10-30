# Progress and stop points

Started **2026-10-29**. Time cap: **6 weeks (until 2026-12-10)**.

Stopping early is a valid outcome. If a stop point below fails, we stop and write the result up as a paper instead of finishing the remaining phases.

<!-- STATUS-START -->
| Phase | What it does | Status | Stop or decision point |
| --- | --- | --- | --- |
| 0 | Repo and foundations | **Done 2026-10-29.** CI green on GitHub; `make check` passes (28 tests) in a fresh Codespace | CI green and `make check` passes on a clean machine |
| 1 | Data feasibility spike | **Done 2026-10-29, Gate G1 passed with conditions.** See [PHASE1_REPORT.md](PHASE1_REPORT.md) | **Gate G1:** every dataset has a data card, a measured fetch cost and a go or no-go |
| 2 | Ingestion pipelines | **Done 2026-10-29.** All five datasets pass the quality report. See [PHASE2_REPORT.md](PHASE2_REPORT.md) | Quality report passes on every dataset |
| 3 | Cost and latency simulator | **Done 2026-10-30, Gate G2 passed.** 24/24 hand calculations, 4/4 AWS calculator readings, 22/22 planted bugs caught. See [PHASE3_REPORT.md](PHASE3_REPORT.md) | **Gate G2:** simulator matches hand calculations and the AWS pricing calculator |
| 4 | Baseline policies, plus seasonal-naive | **Done 2026-10-30. E1: continue by the pre-set rule, narrowly.** Passes only on Azure LRS (no managed tiering there); loses to S3 Intelligent-Tiering and Autoclass everywhere. See [PHASE4_REPORT.md](PHASE4_REPORT.md) | **Early check E1** (below) |
| 5 | Prove the lever, then build the forecast (replaces "Forecast policy", D-036) | **Plan approved 2026-10-30, not started.** Stages 5a (2-6 Nov) and 5b (9-20 Nov). See [PHASE5_PLAN.md](PHASE5_PLAN.md) | **Gate R1 (Fri 6 Nov):** if it fails, the build stops and the paper begins (D-038). **Gate R2 (Fri 20 Nov)** |
| 6 | Freeze and sealed test (stage 5c, 23 Nov to 4 Dec) | Not started | **Gate G3:** go, pivot or stop. The owner creates the freeze tag on GitHub |
| 7 | Robustness | Runs inside the stage 5c pre-registered run (D-043) | H5, H6 and H9 recorded |
| 8 | Compression track | Not started (runs only after G3). Research done 2026-10-30, see [PHASE5_PLAN.md](PHASE5_PLAN.md) | H8 recorded |
| 9 | Live mini-system | Not started (runs only after G3) | 3-minute demo runs from one command |
| 10 | Investor package | Not started | Every number traces to a tagged commit |
| C | Customer conversations (parallel track) | Not started. Starts in week 2 of round two (D-039) | 5-10 conversations with people who run large cold archives |
<!-- STATUS-END -->

## Early check E1 (after Phase 4)

Run the simple "warm what was hot this week last year" policy against the best reactive rival (S3 Intelligent-Tiering, Autoclass, lifecycle rules) on the **2023 validation year only**, at an equal or lower cold-read rate.

- **Stop and rethink** if the gap is under 5% on every real dataset (D1-D4).
- **Continue** if at least one dataset shows 5% or more.

The sealed test years (2024-2025) are not touched at this point.

**Result (2026-10-30):** continue. D1, D3 and D4 each have a passing line, all on Azure (+9.1%, +23.1%, +26.1%); no pass on AWS or Google in any setting. Without flagged series, D1 and D3 fall to +4.2% and +4.5%; on D4 the reactive reference does better than the seasonal policy. The owner decides how to scope Phase 5 ([PHASE4_REPORT.md](PHASE4_REPORT.md)).

## Round two (2026-10-30)

After E1 the owner approved a new Phase 5 ([PHASE5_PLAN.md](PHASE5_PLAN.md), decisions D-036 to D-044). The claim is now "a forecast buys lead time, and lead time buys cheaper restores, at the price of some waiting". The sealed years 2024 and 2025 are still untouched.

| Gate | Date | Result |
| --- | --- | --- |
| R1 | Fri 6 Nov | Not run |
| R2 | Fri 20 Nov | Not run |
| G3 | Fri 4 Dec | Not run |

## Changes from the original plan

These follow the advice given before we started; each is also logged in [DECISIONS.md](DECISIONS.md) (D-003).

1. Added Early check E1 after Phase 4.
2. The seasonal-naive policy moves from Phase 5 into Phase 4 so E1 can run.
3. Compression (Phase 8) and the live demo (Phase 9) run only after Gate G3.
4. Added customer conversations (track C) starting now.
5. Added the 6-week cap.
6. Phase 5 replaced by "prove the lever, then build the forecast", with stop gates R1 and R2 (D-036, D-038).
7. 2023 treated as used; round two develops on rolling years (D-037).
8. Waiting is reported two ways; the Phase 4 rule stays the primary pass rule (D-044).
9. Phases 6 and 7 merge into one pre-registered run (stage 5c) (D-043).
