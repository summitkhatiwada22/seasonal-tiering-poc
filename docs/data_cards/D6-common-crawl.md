# Data card: Common Crawl web archive (D6)

Status: **DEFERRED to Phase 8, after Gate G3.** It is not needed to decide whether forecasting beats reactive tiering, so nothing here blocks G1.

| Field | Value |
| --- | --- |
| Source URL | https://commoncrawl.org (data hosted on Amazon S3 under the AWS Open Data program) |
| Owner / publisher | Common Crawl Foundation |
| Licence or terms | **Not verified.** The only source we could read (a secondary article) says "Crawl data is freely available; individual page copyrights vary." Owner action: read https://commoncrawl.org/terms-of-use before Phase 8. |
| May we use it commercially? | **Unknown.** Individual pages carry their own copyright. |
| Access method | Free download of WARC, WET, WAT and web-graph files |
| Rate limits and required headers | Not checked |
| Date fetched | Not downloaded |
| Raw size on disk | One monthly crawl is very large (the January 2026 crawl was reported at 398 TiB uncompressed, per a secondary source). We would take a few gigabytes. |
| Time coverage | Monthly crawls since 2008 |
| Unit of "object" and "read" | Object = one web page record. There are no reads, so it only tests compression. |
| Manifest file | `manifests/D6.csv` (only if used) |

## Role in the PoC

Compression track only (hypothesis H8): how small can similar web pages be stored, and how fast can one be restored. Pages are not redistributed, only measured.

## Known biases and caveats

- Page copyright varies; we keep a small sample on a private machine, never in the repository.
- Compression ratios depend on the sample. We will report the sample's makeup.

## Cleaning applied

None.
