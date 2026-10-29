# Data card: Wikimedia media file requests, "mediacounts" (D2)

Status: **GO, conditional.** Documentation read 2026-10-29. The fields and file sizes were not visible in what we could read, so the first Phase 2 step is to download one day and inspect it.

| Field | Value |
| --- | --- |
| Source URL | https://dumps.wikimedia.org/other/mediacounts/ (readme read through https://cdimage.debian.org/mirror/wikimedia.org/other/mediacounts/readme.html) |
| Owner / publisher | Wikimedia Foundation (Analytics) |
| Licence or terms | CC0 dedication. Readme: "All Analytics datasets are available under the Creative Commons CC0 dedication." |
| May we use it commercially? | **Yes** for the counts. The images themselves carry their own licences, but we do not download the media. |
| Access method | HTTP file download. A daily folder exists (`mediacounts/daily`). |
| Rate limits and required headers | Not stated. Use a contact User-Agent and polite pacing. |
| Date fetched | Not downloaded yet |
| Raw size on disk | **Unknown. Measure first.** |
| Rows and columns used | To confirm. Expected: file name, number of transfers, possibly bytes transferred. |
| Time coverage | Year folders **2015 to 2026** under `mediacounts/daily/` (first probe did not descend into them; stage 2 does). |
| Unit of "object" and "read" | Object = one media file (image, video or audio). Read = one transfer to a user. |
| Manifest file | `manifests/D2.csv` (Phase 2) |

## What it stands in for

The closest public match to a real file archive: actual files, with actual sizes, requested by people. Readme definition: "Counts of how often an image, video, or audio file from upload.wikimedia.org has been transferred to users."

## Known biases and caveats

- **Fields not yet confirmed.** If there is no byte size per file, D2 has the same size gap as D1.
- **Edge caching** hides some requests from the origin.
- **Viral spikes** (news events) can look seasonal for one year only; the test splits guard against this.

## Cleaning applied

None yet.

## Role in the PoC

Seasonality plus object-size realism. If the fields lack sizes, it drops to a second seasonality dataset.

## Verification

Not done yet. Plan: one downloaded day inspected by hand (schema, row count, ten files cross-checked on Wikimedia Commons).
