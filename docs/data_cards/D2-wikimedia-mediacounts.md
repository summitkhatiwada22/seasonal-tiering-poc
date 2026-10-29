# Data card: Wikimedia media file requests, "mediacounts" (D2)

Status: **GO for object-size calibration only.** Probed 2026-10-29 (`reports/phase2_probe2_2026-10-29.json`). The files are too large to cover three years at our download speed, so D2 is not used for the seasonality test.

| Field | Value |
| --- | --- |
| Source URL | https://dumps.wikimedia.org/other/mediacounts/ (readme read through https://cdimage.debian.org/mirror/wikimedia.org/other/mediacounts/readme.html) |
| Owner / publisher | Wikimedia Foundation (Analytics) |
| Licence or terms | CC0 dedication. Readme: "All Analytics datasets are available under the Creative Commons CC0 dedication." |
| May we use it commercially? | **Yes** for the counts. The images themselves carry their own licences, but we do not download the media. |
| Access method | HTTP file download. A daily folder exists (`mediacounts/daily`). |
| Rate limits and required headers | Not stated. Use a contact User-Agent and polite pacing. |
| Date fetched | Not downloaded yet |
| Raw size on disk | **Measured:** 738 MB (2023-01-01), 869 MB (2023-07-02), 810 MB (2023-12-31) per day, compressed. 365 daily files in 2023, so about 290 GB per year. At 0.65 MB/s one file takes about 20 minutes. |
| Rows and columns used | **25 tab-separated columns.** Observed: column 1 = file path, column 2 = total response bytes, column 3 = total transfers (e.g. a path with 745 bytes and 1 transfer is a 745-byte file). So the average object size is column 2 divided by column 3. The remaining columns are breakdowns by file type and access method; their meaning is to be confirmed against the Wikimedia mediacounts documentation. Lines are sorted by path, not by popularity. |
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
