# Data card: Seattle Public Library checkouts by title (D4)

Status: **GO, conditional on a licence check.** Catalogue page read 2026-10-29; the file itself was not downloaded.

| Field | Value |
| --- | --- |
| Source URL | https://catalog.data.gov/dataset/checkouts-by-title (dataset id `tmmm-ytt6` on data.seattle.gov) |
| Owner / publisher | City of Seattle, Seattle Public Library. Contact on the page: open.data@seattle.gov |
| Licence or terms | **Not stated** on the Data.gov page (access level "public"). Owner action: open the dataset on data.seattle.gov and record the licence line here. |
| May we use it commercially? | **Unknown until the licence line is read.** |
| Access method | CSV export: `https://cos-data.seattle.gov/api/v3/views/tmmm-ytt6/export.csv?accessType=DOWNLOAD` (JSON and XML also offered) |
| Rate limits and required headers | None stated |
| Date fetched | Not downloaded yet |
| Raw size on disk | **Not stated.** Measure first. |
| Rows and columns used | Column list not visible; expected: title, month, checkouts, material type. Confirm on download. |
| Time coverage | April 2005 onward. The page shows "Dataset Last Updated" 2026-09-06. |
| Unit of "object" and "read" | Object = one title. Read = one checkout. |
| Manifest file | `manifests/D4.csv` (Phase 2) |

## What it stands in for

Human demand with obvious yearly rhythm: summer reading, tax guides, school terms, holiday cookbooks. Twenty-plus years of history makes it the longest series we have.

## Known biases and caveats

- **Monthly resolution.** Counts are per month, not per day. We cannot test warm-up windows shorter than about a month, and we must say so in every result that uses D4.
- **Physical items** make checkouts a proxy for demand, not file reads. Electronic items are included.
- **The dataset is updated in place.** Past values might be revised. We keep our own copy and its checksum (decision D-010) and never rely on re-downloading to reproduce a result.
- **Library closures and the 2020 pandemic** distort the data. Treat 2020-2021 with a flag.

## Cleaning applied

None yet.

## Role in the PoC

Long, clean, human seasonality at monthly resolution. Supports the claim "the pattern is real", not the claim "the savings are exactly X".

## Verification

Not done yet. Plan: compare totals for three months against the figures on the data.seattle.gov page.
