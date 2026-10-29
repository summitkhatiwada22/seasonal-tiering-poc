# Data card: Seattle Public Library checkouts by title (D4)

Status: **GO.** Catalogue page and City of Seattle Open Data Policy read 2026-10-29; the file itself was not downloaded. One residual risk is noted under the licence row.

| Field | Value |
| --- | --- |
| Source URL | https://catalog.data.gov/dataset/checkouts-by-title (dataset id `tmmm-ytt6` on data.seattle.gov) |
| Owner / publisher | City of Seattle, Seattle Public Library. Contact on the page: open.data@seattle.gov |
| Licence or terms | The Data.gov page says "No license information was provided" and that the dataset is "covered by different Terms of Use than Data.gov". The governing document is the City of Seattle Open Data Policy (https://www.seattle.gov/documents/Departments/Tech/OpenData/COS_OpenDataPolicy.pdf). Section 3.E: datasets are published "on an open license basis", defined as allowing noncommercial and commercial use without restrictions on copying, publishing, distributing, modifying or using the data. Section 1.D: the City may require users to identify the source and version of a dataset and describe any modifications. |
| May we use it commercially? | **Yes, under the City's open-data policy.** Residual risk: the dataset page carries no licence line of its own, so the policy is the basis. We will cite the dataset and version and describe our changes, as section 1.D allows the City to require. |
| Access method | CSV export: `https://cos-data.seattle.gov/api/v3/views/tmmm-ytt6/export.csv?accessType=DOWNLOAD` (JSON and XML also offered) |
| Rate limits and required headers | None stated |
| Date fetched | Not downloaded yet |
| Raw size on disk | **Unknown.** The server sends no Content-Length (streamed export; a HEAD request reports 0 bytes). Size and row count are found by a full streaming download, timed in stage 2. |
| Rows and columns used | **Observed header:** `UsageClass, CheckoutType, MaterialType, CheckoutYear, CheckoutMonth, Checkouts, Title, ISBN, Creator, Subjects, Publisher, PublicationYear`. Digital (OverDrive) and Physical (Horizon) items. |
| Time coverage | April 2005 onward. The page shows "Dataset Last Updated" 2026-09-06. |
| Unit of "object" and "read" | Object = one title. Read = one checkout. |
| Manifest file | `manifests/D4.csv` (Phase 2) |

## What it stands in for

Human demand with obvious yearly rhythm: summer reading, tax guides, school terms, holiday cookbooks. Twenty-plus years of history makes it the longest series we have.

## Known biases and caveats

- **No stable object id.** ISBN is often blank, so an "object" is identified by Title plus Creator plus MaterialType; duplicates across formats must be merged by rule, recorded in the cleaning section.
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
