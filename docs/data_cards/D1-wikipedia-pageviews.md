# Data card: Wikipedia pageviews (D1)

Status: **GO, with a changed plan.** Probed from the owner's computer on 2026-10-29 (`reports/phase2_probe1_2026-10-29.json`). The daily files are too large to download in bulk (see sizes), so the planned route is the per-article API for a pre-registered article list. A second probe is checking the API and the monthly files.

| Field | Value |
| --- | --- |
| Source URL | https://dumps.wikimedia.org/other/pageview_complete/ (readme: `.../pageview_complete/readme.html`, read through the Debian mirror https://cdimage.debian.org/mirror/wikimedia.org/other/pageview_complete/readme.html) |
| Owner / publisher | Wikimedia Foundation (Analytics) |
| Licence or terms | CC0 dedication. Readme: "All Analytics datasets are released under the Creative Commons CC0 dedication." |
| May we use it commercially? | **Yes.** CC0 places no conditions. |
| Access method | Plain HTTP daily files, folder layout `pageview_complete/YYYY/YYYY-MM/pageviews-YYYYMMDD-{user,spider,automated}.bz2` (93 files in January 2023). Planned instead: Wikimedia per-article pageviews API for a fixed article list. |
| Rate limits and required headers | Not stated on the readme. Send a contact address in the User-Agent and download politely. |
| Date fetched | Not downloaded yet (documentation read 2026-10-29) |
| Raw size on disk | **Measured, per day, compressed (bz2), 2023-01-01:** `user` 463 MB, `automated` 185 MB, `spider` 985 MB. A year of `user` files alone is about 170 GB. Full-file download is **not feasible** on a free, home-internet budget. |
| Rows and columns used | Observed line: `aa.wikipedia Category:User_aa null mobile-web 55 A55` = wiki, title, page id (`null` when unknown), access method, daily total, hourly counts encoded as letters+numbers. Six columns. |
| Time coverage | Year folders **2011 to 2026** on the server (the readme's "December 2007" start does not match what is hosted) |
| Unit of "object" and "read" | Object = one article. Read = one page view. |
| Manifest file | `manifests/D1.csv` (created in Phase 2) |

## What it stands in for

Content that people look up on a schedule: tax articles in spring, holiday topics in December, school subjects each term. It is the cleanest large source of true yearly seasonality.

## Known biases and caveats

- **No object sizes.** A page view says nothing about how many bytes the article holds. The simulator needs a size, so sizes will be drawn from a distribution calibrated on D5 and tested for sensitivity (decision D-009).
- **Pages are cached** by Wikimedia, so views are not storage reads. We are using views as demand, not as measured cold reads.
- **Bots and automated agents.** From 2020 the files flag agent types. We will keep user traffic and report results with and without automated traffic.
- **Download speed.** The first 2 MB of one file took 6.7 seconds (about 0.3 MB/s). That includes start-up delay and is not a sustained rate; stage 2 measures sustained speed.
- **Three traffic types per day** (`user`, `spider`, `automated`) are separate files. Garbage titles from automated probes appear in the `automated` file.
- **Rows without page IDs** (5 columns instead of 6). The readme says a fix is in progress. The parser must handle both.
- **Hours are encoded as letters** (A = hour 0 to X = hour 23).

## Cleaning applied

None yet. Planned: keep user agent type, drop rows with malformed counts, fold hourly counts into daily totals.

## Role in the PoC

Seasonality test, large scale. Train through 2022, validate 2023, sealed test 2024-2025.

## Verification

Not done yet. Plan for Phase 2: choose 20 articles, compare our daily totals with Wikimedia's public per-article statistics.
