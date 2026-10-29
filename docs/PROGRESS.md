# Progress and stop points

Started **2026-10-29**. Time cap: **6 weeks (until 2026-12-10)**.

Stopping early is a valid outcome. If a stop point below fails, we stop and write the result up as a paper instead of finishing the remaining phases.

<!-- STATUS-START -->
| Phase | What it does | Status | Stop or decision point |
| --- | --- | --- | --- |
| 0 | Repo and foundations | **Done 2026-10-29.** CI green on GitHub; `make check` passes (28 tests) in a fresh Codespace | CI green and `make check` passes on a clean machine |
| 1 | Data feasibility spike | Not started | **Gate G1:** every dataset has a data card, a measured fetch cost and a go or no-go |
| 2 | Ingestion pipelines | Not started | Quality report passes on every dataset |
| 3 | Cost and latency simulator | Not started | **Gate G2:** simulator matches hand calculations and the AWS pricing calculator |
| 4 | Baseline policies, plus seasonal-naive | Not started | **Early check E1** (below) |
| 5 | Forecast policy | Not started | Validation results documented, win or lose |
| 6 | Freeze and sealed test | Not started | **Gate G3:** go, pivot or stop |
| 7 | Robustness | Not started | H5, H6 and H9 recorded |
| 8 | Compression track | Not started (runs only after G3) | H8 recorded |
| 9 | Live mini-system | Not started (runs only after G3) | 3-minute demo runs from one command |
| 10 | Investor package | Not started | Every number traces to a tagged commit |
| C | Customer conversations (parallel track) | Not started | 5-10 conversations with people who run large cold archives |
<!-- STATUS-END -->

## Early check E1 (after Phase 4)

Run the simple "warm what was hot this week last year" policy against the best reactive rival (S3 Intelligent-Tiering, Autoclass, lifecycle rules) on the **2023 validation year only**, at an equal or lower cold-read rate.

- **Stop and rethink** if the gap is under 5% on every real dataset (D1-D4).
- **Continue** if at least one dataset shows 5% or more.

The sealed test years (2024-2025) are not touched at this point.

## Changes from the original plan

These follow the advice given before we started; each is also logged in [DECISIONS.md](DECISIONS.md) (D-003).

1. Added Early check E1 after Phase 4.
2. The seasonal-naive policy moves from Phase 5 into Phase 4 so E1 can run.
3. Compression (Phase 8) and the live demo (Phase 9) run only after Gate G3.
4. Added customer conversations (track C) starting now.
5. Added the 6-week cap.
