# Simulator billing rules (Phase 3)

The prices live in `configs/prices/*.yaml`. This file covers the **rules**: how those prices turn into a bill. Every rule is either quoted from an official page (read 2026-10-30, in the Claude desktop app's browser) or listed under "Assumptions" at the end, with the reason.

The simulator works in whole days. One simulated day = one calendar day (UTC). The tier an object sits in on day *d* is the tier it has from 00:00 on day *d*.

## Units

| Rule | AWS | Google | Azure |
| --- | --- | --- | --- |
| U1. 1 GB = 2^30 bytes | "1 GB / 1,073,741,824 bytes" (S3 FAQ worked example) | prices are "per gibibyte" (pricing page) | "binary Gigabytes (GB), where 1 GB = 2^30 bytes" (pricing page) |
| U2. 1 KB = 1,024 bytes (overheads, minimum sizes) | the calculator reproduction tests confirm binary KB | n/a | "base-2 units" (cost-planning page) |

## Storage

| Rule | AWS | Google | Azure |
| --- | --- | --- | --- |
| S1. Daily storage charge | GB-month = byte-hours / hours in that calendar month (S3 FAQ: "x (1 month / 744 hours)"). One day = monthly price / days in that month | "prorated to the sub-second"; price is listed per GiB-**hour**. One day = hourly x 24 = monthly sheet value x 24 / 730 | "average daily amount of data stored ... over a monthly period"; "divide the monthly cost by the number of days that occur in that month". One day = monthly / days in month |
| S2. Minimum billable size | 128 KB for Standard-IA and Glacier Instant (pricing page) | none ("No minimum object size") | none listed |
| S3. Per-object overhead | Glacier Flexible and Deep Archive: 32 KB at the archive rate + 8 KB at the Standard rate (pricing page, footnote ***) | none | Archive: metadata "doesn't exceed 8 KB", billed at the cool tier rate (access-tiers page; see A6) |

## Minimum storage duration (early deletion)

| Rule | AWS | Google | Azure |
| --- | --- | --- | --- |
| E1. What triggers it | object "deleted, overwritten, or transitioned to a different storage class before the minimum storage duration" | delete, replace or move before the minimum; "apply when rewriting objects, such as when you change an object's storage class". **Not** when Object Lifecycle Management changes the class, and not under Autoclass | "deleted, overwritten or moved to a different tier before the minimum number of days" |
| E2. Amount | "pro-rated charge equal to the storage charge for the remaining days" | "charged as if the object was stored for the minimum duration" | "prorated based on the data storage price"; official example: "(180 - 90 days)/30 days x $0.002/GB-month x 1,000 = $6" |
| E3. Simulator formula (remaining days *r*) | *r* x monthly / days in the month the object leaves (A2) | *r* x hourly x 24 | *r* / 30 x monthly (Microsoft's own example) |
| E4. Which clock | days since the object entered its current class | days since the object was **created or last rewritten**: "time spent set at the original storage class counts towards any minimum storage duration that applies for the new storage class" after a lifecycle change | days since the blob was moved to its current tier |

## Moving an object between classes

"Down" means to a colder tier in `tier_order`; "up" means warmer.

| Rule | AWS | Google | Azure |
| --- | --- | --- | --- |
| M1. Down | Lifecycle transition: "Lifecycle Transition request pricing ... represents requests to that storage class" (pricing page) -> `transition_in_per_1000` of the destination. All our down moves are in the supported waterfall | Lifecycle SetStorageClass: "counts as a Class A operation and is billed at the rate that is determined by the destination storage class"; "never ... retrieval fees, or early deletion fees" | "billed as a write operation (per 10,000) to the destination tier" |
| M2. Up from an instantly readable class | COPY onto itself with the new class: PUT/COPY price of the destination, plus the source's retrieval fee (A3), plus early deletion of the source | rewrite: Class A at the destination rate, plus the source's retrieval fee ("read, copy, move, or rewrite"), plus early deletion of the source; clock restarts | "billed as a read from the source tier, where the read operation (per 10,000) and data retrieval (per GB) charges of the source tier apply", plus early deletion |
| M3. Up from an archive class | restore first, then COPY (lifecycle docs): restore request + retrieval of the source, 1 day of temporary copy, PUT of the destination, early deletion of the source. Readable only after the restore time | n/a (no archive class needs restoring) | Set Blob Tier rehydration: archive read operation + archive retrieval, early deletion; "billed as archived data until the data is restored". Readable only after the rehydration time |

## Restoring a temporary copy (pre-warming and on-demand reads)

| Rule | AWS (Glacier Flexible, Deep Archive) | Azure (Archive) |
| --- | --- | --- |
| T1. What it is | "restore a temporary copy of the object ... for a specified duration (number of days)"; the archived object stays put | "Copy an archived blob to an online tier": new blob in Hot; "The source blob remains unmodified in the archive tier" |
| T2. Charges | restore request fee + retrieval per GB (pricing page) + the copy "charged at the S3 Standard storage rate for a duration of time you choose"; the archive keeps being billed | "data read transactions, the amount of data retrieved, and data write transactions for the destination blob. Early deletion fees don't apply"; the copy is billed as Hot storage |
| T3. How long the copy lives | "adding the number of days specified ... to the time when the requested restoration is completed ... then rounds the resulting time to the next day at midnight" (UTC) | the simulator deletes it at the same moment as AWS would (A4), so the two clouds compare like for like; Hot has no minimum duration |
| T4. Asking again while a copy exists | "Subsequent restore requests called on archived objects that have already been restored are billed as GET requests"; the expiry moves relative to the current time | no new copy; the existing copy is kept longer at no request charge |
| T5. Restore time (high / low end) | Flexible: standard 5 / 3 h, bulk 12 / 5 h, expedited 5 / 1 min. Deep Archive: standard 12 h, bulk 48 h (no lower bound stated, so low = high) | standard 15 h (no lower bound stated); high priority 1 h |
| T6. Reads of the copy | GET at the archive class's GET price, no further retrieval fee | Hot read operation, no retrieval fee |

## Reads

| Rule | Detail |
| --- | --- |
| R1 | Each read = one GET (AWS), one Class B operation (Google) or one read operation (Azure) at the current class's rate, plus the class's retrieval fee per GB read. Google: "A retrieval fee applies when you read". AWS: "You pay for retrievals when you GET an object stored in" Standard-IA or Glacier Instant |
| R2 | A read of an archived object with no usable copy triggers an **on-demand restore** that day (standard speed, copy kept 1 day by default). Every read that day waits (see W1) |
| R3 | Egress to the internet is the same for every storage plan, so it is left out by default (option `include_egress`) |

## Waiting

| Rule | Detail |
| --- | --- |
| W1 | Reads are assumed to arrive at the **start** of their day (A1). A read waits until the copy (or the rehydrated object) is readable: wait = ready hour - day start, never below 0 |
| W2 | Two wait totals are reported: **all reads wait** (each read that day waits; upper bound) and **first read waits** (one wait per object-day; lower bound). Both are reported at the high and low end of each restore time (T5) |

## Managed classes (the reactive rivals)

| Rule | AWS S3 Intelligent-Tiering | Google Autoclass |
| --- | --- | --- |
| I1. Tiers by days without access | Frequent < 30 <= Infrequent < 90 <= Archive Instant; optional Archive Access from >= 90 (configurable to 730) and Deep Archive Access from >= 180 | Standard < 30 <= Nearline < 90 <= Coldline < 365 <= Archive (Coldline and Archive only if the terminal class is Archive; default terminal is Nearline) |
| I2. On access | Infrequent / Archive Instant -> Frequent at once. Archive Access / Deep Archive Access: must be restored (standard 3-5 h / within 12 h), then Frequent | object moves to Standard |
| I3. Fees | monitoring $0.0025 per 1,000 objects per month for objects >= 128 KB; "No additional tiering charges"; "no retrieval charges"; restores standard and bulk free; no minimum duration; archive tiers carry the 40 KB overhead | management fee $0.0025 per 1,000 objects per 30 days ("prorated to the millisecond"), objects >= 128 KiB only; "Retrieval fees are not charged"; "Early deletion fees are not charged"; "All operations are charged at the Standard storage rate"; Coldline/Archive -> Standard or Nearline costs one Class A; colder moves and Nearline -> Standard are free |
| I4. Small objects | under 128 KB: always Frequent, no monitoring fee | under 128 KiB: always Standard, no fee |

Azure "smart tier" is available only for zone-redundant storage, which has no price on our LRS sheet, so the simulator refuses it.

## Assumptions (official pages are silent or ambiguous)

| # | Assumption | Why this way | Direction of any error |
| --- | --- | --- | --- |
| A1 | Reads arrive at 00:00 of their day; a restore issued on day *d* starts at 00:00 of *d* | Daily data has no time of day. Start-of-day reads give the longest waits | Waits overstated, never understated, for both us and the rivals |
| A2 | AWS early deletion uses the days in the month the object leaves | AWS bills by byte-hours per month; the remaining days are charged when the object leaves | At most 1/28 of the early-deletion amount |
| A3 | AWS: copying an object out of Standard-IA or Glacier Instant to change its class pays that class's retrieval fee | A copy reads the data; charging it is the cautious choice | Only makes our forecast plan dearer |
| A4 | Azure temporary copies are deleted when an AWS copy with the same days would expire | Like-for-like comparison; Azure has no automatic expiry | Neutral |
| A5 | When an archive object is moved up (M3), billing switches class on the day the move is issued, though data is readable only after the restore time | Day-level model; the gap is at most 2 days (Deep Archive bulk) of storage price difference | Tiny either way |
| A6 | Azure archive metadata = 8 KB per blob at the **cool** rate | Microsoft gives "doesn't exceed 8 KB" and names cool on one page, cold on another; we take the dearer | Makes the archive tier slightly dearer for every plan |
| A7 | Soft delete is off (Google keeps rewritten objects 7 days by default; a bucket owner can set 0). Versioning is off on AWS and Azure | An archive operator controls this setting; the same applies to every plan. Phase 7 re-runs Google with 7 days | Favours plans that rewrite objects (ours) on Google only; checked in Phase 7 |
| A8 | Intelligent-Tiering monitoring fee and Autoclass management fee are prorated by day (monthly fee / days in month; Autoclass fee / 30 per day) | Autoclass says "prorated to the millisecond"; AWS bills per object-month like storage | Tiny |
| A9 | The simulation window's end does not delete anything (no early deletion is charged for objects still stored) | The archive keeps existing | Neutral across plans |
| A10 | Lifecycle (down) moves happen exactly on the day the plan says; provider lag ("asynchronously") is ignored | Lag is unknown and short | Neutral |

## Sources (read 2026-10-30)

| Short name | URL |
| --- | --- |
| S3 pricing page | https://aws.amazon.com/s3/pricing/ (Region US East, N. Virginia) |
| S3 FAQ | https://aws.amazon.com/s3/faqs/ |
| S3 restoring / archived objects | https://docs.aws.amazon.com/AmazonS3/latest/userguide/restoring-objects.html, https://docs.aws.amazon.com/AmazonS3/latest/userguide/archived-objects.html |
| S3 lifecycle transitions | https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-transition-general-considerations.html |
| S3 Intelligent-Tiering | https://docs.aws.amazon.com/AmazonS3/latest/userguide/intelligent-tiering-overview.html, https://aws.amazon.com/s3/storage-classes/intelligent-tiering/ |
| Google pricing page | https://cloud.google.com/storage/pricing |
| Google lifecycle | https://cloud.google.com/storage/docs/lifecycle (section "SetStorageClass cost considerations") |
| Google Autoclass | https://cloud.google.com/storage/docs/autoclass |
| Google soft delete | https://cloud.google.com/storage/docs/soft-delete |
| Azure pricing page | https://azure.microsoft.com/en-us/pricing/details/storage/blobs/ (FAQ holds the $26 rehydration example) |
| Azure access tiers | https://learn.microsoft.com/en-us/azure/storage/blobs/access-tiers-overview |
| Azure rehydration | https://learn.microsoft.com/en-us/azure/storage/blobs/archive-rehydrate-overview |
| Azure cost planning | https://learn.microsoft.com/en-us/azure/storage/common/storage-plan-manage-costs |
