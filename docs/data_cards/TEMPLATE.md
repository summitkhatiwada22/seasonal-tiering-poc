# Data card: <dataset name> (D<number>)

Copy this file to `D<number>-<short-name>.md` and fill every field. Write "unknown" rather than leaving a field empty.

| Field | Value |
| --- | --- |
| Source URL | |
| Owner / publisher | |
| Licence or terms (link to the exact page) | |
| May we use it commercially? | yes / no / unclear (explain) |
| Access method | API / bulk dump / BigQuery / other |
| Rate limits and required headers | |
| Date fetched | |
| Raw size on disk | |
| Rows and columns used | |
| Time coverage | |
| Unit of "object" and "read" | e.g. one Wikipedia article, one page view |
| Manifest file | `manifests/D<number>.csv` |

## What it stands in for

Which real storage workload this is a proxy for, and why.

## Known biases and caveats

For example: bots included, caching hides most reads, monthly instead of daily, renamed objects.

## Cleaning applied

Every filter or fix, in order, with the reason.

## Role in the PoC

Seasonality test, size calibration, or compression track. Which splits (train, validation, sealed test) it feeds.

## Verification

Who checked the totals against the source, on what date, and how (for example, 20 objects compared by hand).
