# Phase 1 report: data feasibility (Gate G1)

Date: 2026-10-29. Author: Claude, reviewed by the project owner.

## Verdict

**Gate G1: PASS, with conditions.** Documentation supports going ahead. Four checks still need a person or a network we do not have here. They are listed under "Open items" and each blocks a specific later step.

## Gate G1 criteria, as stated before Phase 1 began

| Criterion | Result |
| --- | --- |
| At least three real datasets usable | **Met on paper:** D1, D2 and D4 (D3 pending terms). D5 is usable for calibration. |
| At least one with daily reads | **Met:** D1 (daily and hourly), D2 (daily folder), D3 (daily). |
| At least one with clear commercial-use terms | **Met:** D1 and D2 are CC0. |
| A data card per dataset | **Met:** D1-D6 in `docs/data_cards/`. D7 is the synthetic generator (`configs/datasets/synthetic.yaml`). |
| Measured fetch cost per dataset | **Not met.** Every data server is blocked from the build workspace. First step of Phase 2, run from a Codespace or the owner's computer. |

## Summary by dataset

| ID | Dataset | Resolution | Licence | Role | Verdict |
| --- | --- | --- | --- | --- | --- |
| D1 | Wikipedia pageviews | Daily + hourly, 2007 to now | CC0 | Seasonality at scale | **GO** (size to measure) |
| D2 | Wikimedia mediacounts | Daily | CC0 | Seasonality + real file sizes | **GO** (fields to confirm) |
| D3 | npm downloads | Daily, 18-month request cap | Not read | Second seasonality source | **GO if terms allow** |
| D4 | Seattle library checkouts | Monthly, 2005 to now | Not stated | Long human seasonality | **GO if licence allows** |
| D5 | IBM object-store traces | Requests, 7-day spans | SNIA licence, text not seen | Size and re-read calibration | **GO for calibration only** |
| D6 | Common Crawl | No reads | Not verified | Compression track | **DEFERRED** to Phase 8 |
| D7 | Synthetic generator | Daily, 3 years | Ours | Test of the test | **Done** (Phase 0) |

## Price sheets

- **Google Cloud Storage:** verified against Google's own pricing page (us-central1). Storage, retrieval, minimum-duration and operations prices now carry status `sourced` with a link, and a test checks them.
- **AWS:** the official page confirmed the rules (30/90/180-day minimums, 128 KB minimum billable size, 40 KB archive overhead, GET $0.0004). **Its price tables did not render for us**, so per-GB rates remain from secondary articles. Owner action: compare against the AWS Pricing Calculator (us-east-1).
- **Azure:** the official page returned placeholders instead of prices. Only early-deletion periods are confirmed (Cool 30, Cold 90, Archive 180 days). Per-GB prices remain secondary. Owner action: check the Azure pricing calculator, East US.

## Findings that change the plan

1. **Data cannot be downloaded from the build workspace.** Downloads run from a Codespace or the owner's computer (decision D-011).
2. **D1 and D3 have no object sizes.** Sizes will be modelled from D5, with a sensitivity test (D-009).
3. **D4 is monthly only.** Results from D4 will state that limit (D-010).
4. **D5 cannot test seasonality** (7-day spans). It is a calibration source.
5. **Free multi-region prices differ** from single-region. We model single region only (D-008).

## Open items

| # | Item | Who | Blocks |
| --- | --- | --- | --- |
| 1 | Read the SNIA download licence text; record commercial-use answer in D5 card | Owner | Using D5 in investor material |
| 2 | Read Seattle licence line on data.seattle.gov; record in D4 card | Owner | Using D4 |
| 3 | Read npm API terms; record in D3 card | Owner | Using D3 |
| 4 | Compare AWS and Azure per-GB prices with each provider's calculator | Owner | Gate G2 (simulator check) |
| 5 | Measure real file sizes and download speed from a Codespace | Phase 2, step 1 | Phase 2 plan |
| 6 | Confirm mediacounts fields and date range after one sample download | Phase 2, step 1 | D2 role |
