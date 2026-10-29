# Data card: IBM Cloud Object Storage traces (D5)

Status: **GO for calibration only. Not a seasonality dataset.** Catalogue page and licence text read 2026-10-29.

| Field | Value |
| --- | --- |
| Source URL | https://iotta.snia.org/traces/key-value/36305 (SNIA IOTTA repository, "IBM Object Store") |
| Owner / publisher | IBM Research, hosted by SNIA IOTTA |
| Licence or terms | SNIA Trace Data Files Download License (https://iotta.snia.org/repository/download_license, read 2026-10-29). Permissive, MIT-style: use, copy, modify, distribute, sublicense and sell copies "without restriction". Condition: keep the copyright notice (Copyright (c) 2008 SNIA) and permission notice in copies. Provided "AS IS", no warranty. Terms must be accepted to download. |
| May we use it commercially? | **Yes.** The licence grants the right to sell copies. Condition: keep the SNIA notice if the data is redistributed. We will not redistribute the traces, only results computed from them. |
| Access method | Browser download with cookies enabled. The page links to shell-script and batch-script guides. No registration stated. |
| Rate limits and required headers | None stated |
| Date fetched | Page reachable from the owner's computer on 2026-10-29 (HTTP 200); no trace downloaded yet |
| Raw size on disk | 110 traces. Listed files range from 3.78 MB to 731 MB (traces 000-004). Trace 005 comes in five parts of about 880-900 MB each. Total not stated. |
| Rows and columns used | **Not listed** on the catalogue page. Expect operation type, object id and size. Confirm on download. |
| Time coverage | Recorded in 2019. **Each trace covers about 7 days, or about 1 day for the large trace parts.** |
| Unit of "object" and "read" | Object = one stored object. Read = one GET request. |
| Manifest file | `manifests/D5.csv` (Phase 2) |

Citation named on the page: Eytan, Harnik, Ofer, Friedman, Kat, "It's Time to Revisit LRU vs. FIFO", HotStorage '20.

## What it stands in for

A real production object store. It tells us how big real objects are and how often a stored object is read again.

## Known biases and caveats

- **Too short for seasonality.** Seven days cannot show a yearly pattern. We use D5 only to calibrate object sizes and the share of data that is read again, never to test the forecaster.
- **One provider and one year.** Do not generalise beyond the stated mix.
- **Large downloads.** One part is about 0.9 GB. Fetch only what the calibration needs.

## Cleaning applied

None yet.

## Role in the PoC

Provides the object-size distribution used for D1, D3 and D4 (decision D-009), and the read-again statistics for the simulator.

## Verification

Not done yet. Plan: reproduce the record count and size shown on the catalogue page for one trace.
