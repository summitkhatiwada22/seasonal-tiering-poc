# Data card: npm package downloads (D3)

Status: **GO, conditional on a terms check.** Facts below come from a third-party article that describes the API (the npm documentation page itself was not reachable). The terms of use have not been read.

| Field | Value |
| --- | --- |
| Source URL | https://api.npmjs.org/downloads/ (endpoints `point` and `range`) |
| Owner / publisher | npm, Inc. (GitHub / Microsoft) |
| Licence or terms | **Not read yet.** Owner action: read npm's API terms before Phase 2 and record the result here. |
| May we use it commercially? | **Unknown.** |
| Access method | REST API, one package per request |
| Rate limits and required headers | Rate limiting occurs; no numbers published in our source. Plan: sequential requests, short delay, exponential backoff. |
| Date fetched | Not downloaded yet |
| Raw size on disk | Small (daily counts per package). Estimate only: kilobytes per package. |
| Rows and columns used | Date, package name, downloads |
| Time coverage | **A single request covers about 18 months (about 549 days).** Longer requests are truncated without warning. History back to 2015 is reachable by chunking the range, per the article. |
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

Second real seasonality source with a different audience. Lower priority than D1 and D2. Drop it if the terms forbid our use.

## Verification

Not done yet. Plan: sum our chunks and compare with the single-request total for a recent 90-day window.
