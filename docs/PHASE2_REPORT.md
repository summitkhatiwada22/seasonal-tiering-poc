# Phase 2 report: ingestion

Date: 2026-10-29. Verdict: **PASS.** All five datasets pass the quality report (`data_records/reports/quality_report.md`).

All downloads ran on the owner's Mac onto a 32 GB flash drive (the build workspace cannot reach the data servers, D-011). The raw data and Parquet files are not in the repository; only records are (lists, flags, checksums, summaries, the report) in `data_records/`.

## What was downloaded

| Dataset | What | Size | Result |
| --- | --- | --- | --- |
| D1 Wikipedia | Daily user page views, 2016-01-01 to 2025-12-31, 10,000 articles: cohort A = 5,000 most viewed (pre-2023 ranking), cohort B = 5,000 random ordinary articles | 36.5 million rows; 483 MB raw, 53 MB Parquet | Pass: rows = items x days, no duplicates, all listed items present, 84 checksums re-verified |
| D3 npm | Daily downloads, same span, 300 packages (top 100 of the npm-high-impact ranking plus 200 drawn with seed 20261029 from ranks 101-5000) | 1.1 million rows | Pass |
| D4 Seattle | Monthly checkouts per title, 2005 to 2026-09, all years | 51,804,190 rows; 6.8 GB raw, 2.0 GB Parquet | Pass: every year matches the server row count; 1,045 checksums re-verified |
| D2 mediacounts | One day (2023-07-02) for object sizes | 33.1 million media files | Median about 25 KB, mean about 200 KB, 99th percentile about 3.9 MB (bytes per transfer) |
| D5 IBM traces | Two traces (002 part 0, 004 part 0) | 0.4 M and 9.9 M requests | Format guess confirmed (0 unparsed lines); sizes vary from bytes to 100s of MB |

## Findings worth knowing

1. **The data pipeline agrees with Wikipedia's own numbers.** In the 50-article pilot, 740 of 740 article-months matched the server's monthly top lists exactly.
2. **Cohorts differ a lot.** Cohort A: median 10.8 million views over 2016-2022, 853 bursty and 54 thin articles. Cohort B: median 3,280 views, 201 bursty and 1,135 thin. Results will be reported per cohort and with and without flagged articles (D-019).
3. **Flags overall:** D1 1,054 bursty and 1,189 thin of 10,000. D3 16 bursty and 43 thin of 300 (the 16 and 43 include articles flagged both ways).
4. **A title filter cannot catch all automated traffic** (for example XHamster stays in cohort A). The flags and with/without reporting are the safeguard.
5. **The monthly top-pages list has gaps that change between runs.** The pilot found no list for 2020-07; the full run found none for 2016-08 and 2017-11 (all within the 3-month tolerance, D-018). The saved article list is the pre-registered cohort, so this does not affect reproducibility, but a fresh `list` run could pick a slightly different cohort A.
6. **Sizes differ by orders of magnitude between sources** (Wikipedia media median 25 KB; IBM trace 004 median 59 KB with a large group near 17 MB, mean 20 MB). Every result must be shown at low, central and high size settings (D-009).
7. **D5 is not a read-again source.** The traces only contain objects that were requested; 99.98% of GETs hit objects read two or more times, which says nothing about how much stored data is never read.
8. **D4 specifics:** 2020 is low (pandemic closure) and 2026 stops in September; the data is monthly; titles have no stable ID (matching rule to be fixed in Phase 4). D4 is updated in place by the publisher, so our raw copy is the record (D-010).

## Sealed years

2024-2025 (D1, D3) and the 2024-2026 rows in D4 are on disk but not examined. No analysis has touched them. A loader guard that refuses to read them before the freeze is a Phase 4 task.

## Open items carried forward

Status as of 2026-10-30:

- ~~AWS retrieval and request fees~~ Done: every AWS, Azure and Google price is now read from an official source (D-025); no value is unverified.
- Back up the raw D4 copy and the Parquet files to a second place (the flash drive is the only copy). **Owner's decision: no backup; the flash drive stays the only copy.** If the drive fails, the downloads can be repeated from the saved lists, but D4 is updated in place by its publisher and may have been revised by then (D-010), so a re-download could change numbers already reported.
- ~~Remove the stale `processed/D5/trace_summary.json`~~ Done: only the per-trace files remain.
- Model reminder for Phase 3 was given; the owner chooses the model.
- Still to do: sealed-year loader guard (Phase 4); manual freeze tag on GitHub (Phase 6, tag pushes fail from the build workspace); read Common Crawl terms (Phase 8).
- Data integrity re-check on 2026-10-30, run independently of the pipeline code: all 1,135 files listed in the manifests (D1 84, D2 1, D3 3, D4 1,045, D5 2; 9.4 GB) are present at the recorded size and their SHA-256 matches. Nothing has changed since Phase 2.
