# Data card: Wikipedia pageviews (D1)

Status: **GO, conditional.** Checked 2026-10-29 from published documentation only. The data servers cannot be reached from the build workspace, so size and download speed are not yet measured.

| Field | Value |
| --- | --- |
| Source URL | https://dumps.wikimedia.org/other/pageview_complete/ (readme: `.../pageview_complete/readme.html`, read through the Debian mirror https://cdimage.debian.org/mirror/wikimedia.org/other/pageview_complete/readme.html) |
| Owner / publisher | Wikimedia Foundation (Analytics) |
| Licence or terms | CC0 dedication. Readme: "All Analytics datasets are released under the Creative Commons CC0 dedication." |
| May we use it commercially? | **Yes.** CC0 places no conditions. |
| Access method | Plain HTTP file download of daily files (bzip-compressed) |
| Rate limits and required headers | Not stated on the readme. Send a contact address in the User-Agent and download politely. |
| Date fetched | Not downloaded yet (documentation read 2026-10-29) |
| Raw size on disk | **Unknown. Measure first** (Phase 2, step 1) |
| Rows and columns used | Wiki code, article title, page ID (where present), daily total, hourly counts |
| Time coverage | December 2007 to present, per the readme |
| Unit of "object" and "read" | Object = one article. Read = one page view. |
| Manifest file | `manifests/D1.csv` (created in Phase 2) |

## What it stands in for

Content that people look up on a schedule: tax articles in spring, holiday topics in December, school subjects each term. It is the cleanest large source of true yearly seasonality.

## Known biases and caveats

- **No object sizes.** A page view says nothing about how many bytes the article holds. The simulator needs a size, so sizes will be drawn from a distribution calibrated on D5 and tested for sensitivity (decision D-009).
- **Pages are cached** by Wikimedia, so views are not storage reads. We are using views as demand, not as measured cold reads.
- **Bots and automated agents.** From 2020 the files flag agent types. We will keep user traffic and report results with and without automated traffic.
- **Rows without page IDs** (5 columns instead of 6). The readme says a fix is in progress. The parser must handle both.
- **Hours are encoded as letters** (A = hour 0 to X = hour 23).

## Cleaning applied

None yet. Planned: keep user agent type, drop rows with malformed counts, fold hourly counts into daily totals.

## Role in the PoC

Seasonality test, large scale. Train through 2022, validate 2023, sealed test 2024-2025.

## Verification

Not done yet. Plan for Phase 2: choose 20 articles, compare our daily totals with Wikimedia's public per-article statistics.
