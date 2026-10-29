# Data card: npm package downloads (D3)

Status: **GO, low risk.** npm's open-source terms and crawler policy were read on 2026-10-29. Neither names download statistics specifically. API facts come from a third-party article because npm's own API page was not reachable.

| Field | Value |
| --- | --- |
| Source URL | https://api.npmjs.org/downloads/ (endpoints `point` and `range`) |
| Owner / publisher | npm, Inc. (GitHub / Microsoft) |
| Licence or terms | npm Open-Source Terms (https://docs.npmjs.com/policies/open-source-terms/) and Crawler policy (https://docs.npmjs.com/policies/crawlers/), read 2026-10-29. Public documented APIs may be used; automated crawling of the Website is prohibited; requests must not be an "unreasonable volume" (the terms name five million requests a month by one party as not reasonable); commercial use of npm Open Source is allowed. The crawler policy asks experimental crawlers to stay at 1 request per second or less and says npm may rate-limit or ban an IP or user-agent. |
| May we use it commercially? | **Yes for npm open source and its public APIs. Neither document names download statistics,** so we treat the download-count API as a public documented API and keep within the stated limits. |
| Access method | REST API, one package per request |
| Rate limits and required headers | Stay at or below 1 request per second (crawler policy), far below five million requests a month. Sequential requests, backoff on errors. A few hundred packages in chunks is a few thousand requests in total. |
| Date fetched | Not downloaded yet |
| Raw size on disk | Small (daily counts per package). Estimate only: kilobytes per package. |
| Rows and columns used | Date, package name, downloads |
| Time coverage | **Confirmed by test on 2026-10-29:** a request for 2020-01-01 to 2023-01-01 (3 years) returned 550 days, 2021-07-01 to 2023-01-01, with no error. The API silently keeps the **end** of the range. History before that needs chunks of 500 days or fewer. A 10-day request returned all 10 days correctly. |
| Unit of "object" and "read" | Object = one package. Read = one download. |
| Manifest file | `manifests/D3.csv` (Phase 2) |

Source for the facts above: https://tanstack.com/blog/npm-stats-the-right-way (secondary source, read 2026-10-29).

## What it stands in for

Software artefacts with school-term, holiday and release-cycle rhythms. Daily resolution.

## Known biases and caveats

- **Silent truncation.** A request longer than about 18 months returns less than asked, with no error. The loader must fetch in chunks of 500 days or fewer and assert that it received every date.
- **CI/CD and mirrors dominate downloads.** Many "downloads" are automated builds, which suit weekday patterns but not human seasonality.
- **No bulk endpoint** (per our source), so we must choose packages in advance. The package list is a decision, recorded in `docs/DECISIONS.md` before fetching, to avoid cherry-picking.
- **No object sizes** in the counts; tarball sizes come from registry metadata.
- **Weekly pattern is very strong,** which is useful for testing the weekly category but not yearly seasonality.

## Cleaning applied

None yet.

## Role in the PoC

Second real seasonality source with a different audience. Lower priority than D1 and D2. If npm later objects to this use, drop it.

## Verification

Not done yet. Plan: sum our chunks and compare with the single-request total for a recent 90-day window.
