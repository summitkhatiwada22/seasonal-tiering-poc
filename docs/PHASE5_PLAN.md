# Phase 5 plan (round two): prove the lever, then build the forecast

Approved by the owner on **2026-10-30**. **Status (2026-10-30): stage 5a done, gate R1 failed narrowly, stage 5b not built (D-050). Results: [PHASE5_REPORT.md](PHASE5_REPORT.md). The owner then ran the sealed test once as a documented deviation (D-051); Gate G3 failed and the paper is being written (D-052, [RESULTS.md](RESULTS.md)).** It replaces the old Phase 5 ("build a real forecast"). The reasons and the exploratory evidence are in the research document "Improving the numbers: research and new plan" (Claude Docs). Decisions are D-036 to D-044 in [DECISIONS.md](DECISIONS.md).

The probe scripts and outputs behind the evidence are in [scripts/probes/2026-10-30/](../scripts/probes/2026-10-30/README.md). They use data up to 2022 only. They are exploratory and are not a result.

## The claim, restated

Old claim: "seasonal forecasting beats reactive auto-tiering."

New claim: **a forecast buys lead time, and lead time buys cheaper restores (deep tiers and bulk restores), at the price of some waiting.** Seasonality is one input to the forecast, not the product. The claim is judged under the waiting rule in D-044.

## Why the plan changed (2022 data, exploratory)

| Finding | Number |
| --- | --- |
| Only npm (D3) has a stable yearly season | Season strength 0.85 on npm, 0.40 on Wikipedia, 0.15 on the library data |
| "Same days last year" is a worse forecast than a plain yearly average on every dataset, even when read noise is removed | Error 0.34 vs 0.18 (npm), 0.46 vs 0.35 (Wikipedia), 0.99 vs 0.69 (library) |
| On AWS the planner loses to Intelligent-Tiering even when told each file's true expected rate | -14.1% Wikipedia, -13.0% npm, at up to 1% waiting. The decision rule, not the forecast, is the bottleneck there |
| The library data (D4) is where a better forecast matters | Pooled forecast -52.6%, true rate -4.6%, last year's reads -72.9% (AWS, up to 1% waiting) |
| Bulk restores trade waiting for money | Pick 2021, score 2022, equal 1% allowance: +13.2% (Wikipedia), +16.0% (npm), -14.5% (library). With the Phase 4 rule (no more waiting than the rival): -4.5%, -6.9%, -16.4%. Share of reads that wait: 0.80% vs 0.25% (Wikipedia) |
| True rate plus bulk restores wins on the library data only | +16.7% at up to 1% waiting (+27.2% at none); Wikipedia -19.4%, npm -15.6% |
| The bill is set by a few big files | The largest 1% of files hold 49% to 53% of the bytes; 55% of files are under 128 KB and hold 0.05% to 0.08% |

## Stages and gates

| Stage | Dates | Work | Gate |
| --- | --- | --- | --- |
| 5a. Prove the lever | Mon 2 Nov to Fri 6 Nov | Write down the waiting rule (D-044). Planner prices bulk restores and matches lead time to the 12-hour and 48-hour restore times. Exact per-file optimizer. Forecastable ceiling (true expected rate, not the random draw). Zone-redundant Azure sheet and smart tier as the Azure rival | **R1, Fri 6 Nov** |
| 5b. Build the forecast | Mon 9 Nov to Fri 20 Nov | Rate and trend forecasts (pooled, shrunk), calendar features where a dataset has them, robustness layer, real npm sizes, compression sizing test if approved (open item below) | **R2, Fri 20 Nov** |
| 5c. Freeze and sealed test (Phase 6, with the Phase 7 scenarios in the same pre-registered run) | Mon 23 Nov to Fri 4 Dec | Write and tag PREREGISTRATION.md (the owner creates the tag on GitHub), run once on 2024 and 2025, RESULTS.md | **G3, Fri 4 Dec** |
| Write-up (Phase 10 or the paper) | Mon 7 Dec to Thu 10 Dec | Memo or paper, every number traced to a tagged commit | Deadline |

Phases 8 (compression) and 9 (live mini-system) still run only after G3, and only in reduced form if G3 passes. If it does not, they become future work in the write-up.

### Gate R1 (Fri 6 Nov)

Passes if both hold:

1. Under the waiting rule in D-044, a method beats the best AWS rival by 5% or more in **both** rolling years (pick 2021, score 2022; pick 2020, score 2021 where the data allow) on at least two of D1, D3 and D4.
2. The exact optimizer, told each file's true expected rate, beats the best AWS rival by 10% or more on at least two of D1, D3 and D4.

**If R1 fails: the build stops and the paper begins.** The deadline does not move (D-038).

### Gate R2 (Fri 20 Nov)

Passes if a forecast closes at least half of the gap between the reactive policy and the forecastable ceiling, in rolling years, on two datasets. If it fails, we keep the lever and the optimizer and drop the claim that forecasting skill adds value.

### Gate G3 (Fri 4 Dec)

The pre-registered thresholds, run once on the sealed 2024 and 2025 data. Round two adds only the stronger Azure rival and the bulk-aware policies to the list written down before the data is opened. If G3 fails, we report as found.

## Rules for round two

1. **2024 and 2025 stay sealed.** Nothing in round two opens them. The folder-name lock and its tests stay as they are. Only G3 opens them, once.
2. **2023 has been used.** E1 scored it once. Any new method scored on 2023 is a second look and is labelled as one. At most one labelled second look, at 5c (D-037).
3. **Develop on rolling years.** Choose settings on year Y-1, score on year Y, for 2021 and 2022 (and 2020 where the data allow).
4. **Write the test before running it.** Before the first scoring run, the list of new methods, every setting, the pick rule and the pass bar are committed and pushed, as in E1. The commit order is the proof.
5. **Count the options.** Ours has far more settings than the rival (48 against 15 in the AWS bulk test), so every claim is made on a year the settings did not see, and a pass has to hold in more than one rolling year.
6. **Keep the rival real.** No Azure claim is made against "keep everything hot" (D-041). AWS rivals include Intelligent-Tiering with and without its archive tiers.
7. **Use the forecastable ceiling, not the lucky one.** The old "perfect forecast" knows which days a random read lands on, which no forecast can. Round two judges forecasts against a ceiling that knows each file's true expected rate but not the random draw.
8. **Report every line,** passing and failing, all datasets and clouds.
9. **New datasets are split before they are looked at.** The last two years are sealed by folder name from the day the dataset is added (D-040).
10. **A second pair of eyes.** Someone other than the author re-derives a sample of the hand calculations.
11. **Stop rules are fixed in advance** (R1 above).
12. **Waiting is reported two ways** (D-044): the primary pass rule is "ours waits no more than the rival"; the second result is an equal 1% allowance plus total waiting hours. A pass on the second only is reported as a trade-off, not a pass.

## Work order in 5a

1. Commit this plan, the waiting rule and the settings list before scoring anything.
2. Planner prices bulk restores (it currently hard-codes standard fees in `planner.py`) and chooses lead times to match the 12-hour and 48-hour restore times.
3. Per-file optimizer: each file's cheapest path through the storage classes with every fee counted, given its expected rate.
4. Forecastable-ceiling policy and a rolling-year scoring script (matched-waiting and equal-allowance, with waiting hours).
5. Azure zone-redundant price sheet (official Retail Prices API) and smart tier as the Azure rival.
6. Report every line; record R1.

## Asks of the owner

- At 5c: create the freeze tag on GitHub (tag pushes are blocked from the workspace).
- In 5b: real npm sizes are fetched from the workspace; the Wikimedia Commons file-request dataset needs the owner's computer (the workspace gets HTTP 403).
- Customer conversations (track C) start in week 2: three conversations, each asking for one real access log and one example of a restore planned in advance (D-039).
- Before 5c: confirm the wording of H1 (see open items).

## Compression: research summary and plan

Compression is separate from the tiering comparison: both sides store the same files, so compression lowers every bill and **stacks** with tiering savings. It is reported separately and never counted as a tiering win. The research found no single better method; the fit depends on the file type, which D1 to D4 do not tell us (they hold counts, not bytes).

| Technique | Evidence read | Fit for us | Plan |
| --- | --- | --- | --- |
| Stronger general codec (zstd high levels, xz) | One structured file: zstd -3 ratio 1.31 at 220 MB/s compress; xz -9 ratio 1.64 at 3.5 MB/s compress and 45 MB/s decompress (Meta OpenZL post, M1 CPU). On Wikipedia text zstd is competitive with xz and decodes fastest (Rosato) | Text-like content: WARC, logs, tarballs | Phase 8 baseline against gzip, several levels, on real files |
| Trained dictionaries for small files | zstd docs: gains largest under about 100 KB; needs about 100x the dictionary size in samples; "2x or more" is stated, not measured | Small files hold 0.05% to 0.08% of the bytes, so little storage effect | Measure in Phase 8; low priority |
| Bundling small objects, with seekable frames | AWS sheet: 40 KB of overhead per archived object, which equals the data cost of an object of 218 KB in Deep Archive and 83 KB in Glacier Flexible (arithmetic from `configs/prices/aws.yaml`). zstd seekable format reads one frame; frames under 1 KB compress badly | Removes per-object overhead and transition fees; a read restores the whole bundle, so group files likely to be read together | Measure in Phase 8; idea to test later: group by forecast read season |
| Deduplication | Whole-file dedup recovers about three quarters of block-level savings on 857 desktops, 87% on backup images (Meyer and Bolosky, FAST 2011) | npm versions of one package share most files; duplicate payloads in web archives | Whole-file hash first (already in Phase 8); chunk-level only if it adds enough |
| Format-aware recompression of JPEG | Lepton: 22% smaller, bit-exact, encode about 5 MB/s, decode about 15 MB/s, under 24 MB memory; Dropbox had encoded 16 billion images. JPEG XL lossless JPEG recompression: about 20%, byte-exact reconstruction | Image-heavy archives such as Wikimedia Commons | Test on a Commons sample on the owner's computer |
| Format-aware coding of structured data | OpenZL: ratio 2.06 on one star catalog at 340 MB/s compress, 1,200 MB/s decompress; no advantage on unstructured text | Tables and logs such as D4 records | Optional test on the owner's computer |
| Joint choice of tier, partition and codec | SCOPe (Adobe, arXiv 2305.14818): ILP over partitions, codecs and tiers; savings of 8% to 11.6% over 2 months and 49.6% to 83.7% over 6 months on an enterprise data lake, against a premium-tier baseline; gzip-ratio prediction error about 0.5% on TPC-H | Different baseline and workload; not a comparison with Intelligent-Tiering | Idea only: predict a codec's ratio from a small sample before choosing |
| AI-based compressors | Chinchilla 70B: 43.4% of raw size on ImageNet patches (PNG 58.5%), 16.4% on LibriSpeech (FLAC 30.3%) (Deletang et al., ICLR 2024) | A 70B-parameter model per file is not an economic storage method | Keep the existing optional 10 MB timing run; do not pursue |

**When heavier compression pays.** Compute is a one-off cost and storage savings repeat every month, so the break-even time depends on the tier price. Using the speeds above, an assumed USD 0.04 per core-hour (assumed, not from a price page), and an extra 10% to 20% saving of xz -9 over zstd -3: break-even is 0.7 to 1.5 months in S3 Standard, 4.7 to 9.3 months in Glacier Flexible and 16.9 to 33.9 months in Deep Archive. Heavy codecs pay where data is expensive or will sit for years; fast codecs suit data that may be restored soon. Decompressing 1 TB with xz at 45 MB/s costs about USD 0.25 of compute on the same assumption.

**Interaction with tiering.** Objects under 128 KB are never tiered by Intelligent-Tiering and are billed as 128 KB in the infrequent classes, so compressing a small object saves nothing there; bundling is the lever for small files and compression for the large ones, which hold half the bytes.

## Open items for the owner

- **A half-day compression sizing test in 5b:** download about 100 MB of public npm tarballs (the D3 packages) from registry.npmjs.org and measure gzip, zstd and xz, cross-version dedup and a trained dictionary. Needs the owner's yes before any download.
- **H1 wording before the freeze.** The plan says "3 of 4 long-history datasets", but only three datasets have real multi-year demand (D1, D3, D4); D2 is size calibration only (D-015). The owner confirms the pass rule at 5c. Proposed: at least 5% cheaper under the D-044 rule in each sealed year on at least two of the three, 95% interval above zero, with 15% reported as the target.
- **Git history.** The 79 MB of arrays in commit d1cf04d are left in history. A purge needs a force-push and is the owner's call.
