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
| D3 | npm downloads | Daily, 18-month request cap | npm open-source terms: commercial use allowed, public APIs permitted, stay at 1 request/second | Second seasonality source | **GO** (low risk) |
| D4 | Seattle library checkouts | Monthly, 2005 to now | City open-data policy: open licence, commercial use allowed | Long human seasonality | **GO** |
| D5 | IBM object-store traces | Requests, 7-day spans | SNIA licence: MIT-style, commercial use allowed | Size and re-read calibration | **GO for calibration only** |
| D6 | Common Crawl | No reads | Terms page unreadable | Compression track | **DEFERRED** to Phase 8 |
| D7 | Synthetic generator | Daily, 3 years | Ours | Test of the test | **Done** (Phase 0) |

## Price sheets

- **Google Cloud Storage:** verified against Google's own pricing page (us-central1). Storage, retrieval, minimum-duration and operations prices now carry status `sourced` with a link, and a test checks them.
- **AWS:** the official page confirmed the rules (30/90/180-day minimums, 128 KB minimum billable size, 40 KB archive overhead, GET $0.0004). The owner's calculator readings (10 GB per month, rounded to cents) agree with our per-GB prices within rounding: Standard 0.02, Glacier Instant 0.04, Glacier Flexible 0.04, Deep Archive 0.01. They cannot confirm the third decimal, so a re-read at 10,000 GB is still wanted before Gate G2.
- **Azure:** the owner's screenshot of Azure's own table (Hot 0.0184, Cool 0.01, Cold 0.0036, Archive 0.002 per GB per month) is saved in `docs/evidence/`. **It exposed two wrong values in our sheet**: Cold was 0.0045 and Archive was 0.00099 (an AWS figure). Both are corrected and a test now guards them. Region and redundancy are not visible in the image; we assume East US, LRS. Retrieval prices still come from secondary sources.

## Findings that change the plan

1. **Data cannot be downloaded from the build workspace.** Downloads run from a Codespace or the owner's computer (decision D-011).
2. **D1 and D3 have no object sizes.** Sizes will be modelled from D5, with a sensitivity test (D-009).
3. **D4 is monthly only.** Results from D4 will state that limit (D-010).
4. **D5 cannot test seasonality** (7-day spans). It is a calibration source.
5. **Free multi-region prices differ** from single-region. We model single region only (D-008).

## Licences (read by Claude on 2026-10-29)

| Dataset | Result | Where |
| --- | --- | --- |
| D1, D2 | CC0, no conditions | Wikimedia readmes |
| D5 | SNIA licence allows commercial use; keep the SNIA notice if redistributing | iotta.snia.org/repository/download_license |
| D4 | City of Seattle Open Data Policy requires an open licence allowing commercial use; the dataset page itself shows no licence line | seattle.gov Open Data Policy, sections 1.D and 3.E |
| D3 | npm terms allow commercial use and public APIs; download statistics are not named; keep to 1 request per second | docs.npmjs.com open-source terms and crawler policy |
| D6 | Terms of Use page would not load; deferred | commoncrawl.org/faq |

None of this is legal advice. Before any investor material relies on D3 or D4, a lawyer can confirm it in an hour.

## Open items

| # | Item | Who | Blocks |
| --- | --- | --- | --- |
| 1 | AWS calculator re-read at 10,000 GB (exact decimals); confirm the Azure screenshot's region and redundancy; read Azure and AWS retrieval fees | Owner (10 minutes) | Gate G2 (simulator check) |
| 2 | Measure real file sizes and download speed from a Codespace or the owner's computer | Phase 2, step 1 | Phase 2 plan |
| 3 | Confirm mediacounts fields and date range after one sample download | Phase 2, step 1 | D2 role |
| 4 | Read Common Crawl Terms of Use | Phase 8, before use | Compression track only |
