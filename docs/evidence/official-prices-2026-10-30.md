# Official price evidence, read 2026-10-30

Read by Claude in a real browser (the Claude desktop app's browser on the owner's computer), from each provider's own pages or price data. Rows are copied as the pages showed them. These are the sources for `configs/prices/*.yaml`.

## AWS S3, US East (N. Virginia)

Source: https://aws.amazon.com/s3/pricing/ with Region set to US East (N. Virginia). The page fills its tables from https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/s3/USD/current/s3.json (publication date 2026-10-15T17:35:40Z).

### Storage pricing

| Row | Price |
| --- | --- |
| S3 Standard, first 50 TB / month | $0.023 per GB |
| S3 Standard, next 450 TB / month | $0.022 per GB |
| S3 Standard, over 500 TB / month | $0.021 per GB |
| Intelligent-Tiering monitoring and automation, objects > 128 KB | $0.0025 per 1,000 objects |
| Intelligent-Tiering Frequent Access, first 50 TB | $0.023 per GB |
| Intelligent-Tiering Infrequent Access | $0.0125 per GB |
| Intelligent-Tiering Archive Instant Access | $0.004 per GB |
| Intelligent-Tiering Archive Access (optional) | $0.0036 per GB |
| Intelligent-Tiering Deep Archive Access (optional) | $0.00099 per GB |
| S3 Standard-Infrequent Access | $0.0125 per GB |
| S3 Express One Zone | $0.11 per GB |
| S3 Glacier Instant Retrieval | $0.004 per GB |
| S3 Glacier Flexible Retrieval | $0.0036 per GB |
| S3 Glacier Deep Archive | $0.00099 per GB |
| S3 One Zone-Infrequent Access | $0.01 per GB |

Footnote (Glacier Flexible Retrieval, Deep Archive): "AWS charges for 40 KB of additional metadata for each archived object, with 8 KB charged at S3 Standard rates and 32 KB charged at S3 Glacier Flexible Retrieval or S3 Deep Archive rates." Glacier Instant Retrieval, Standard-IA and One Zone-IA have a minimum billable object size of 128 KB. Minimum storage duration: Standard-IA 30 days, Glacier Instant and Flexible 90 days, Deep Archive 180 days.

### Requests and data retrievals

Columns: PUT, COPY, POST, LIST (per 1,000) | GET, SELECT and other (per 1,000) | lifecycle transition into (per 1,000) | data retrieval requests (per 1,000) | data retrievals (per GB)

| Class | PUT | GET | Transition in | Retrieval requests | Retrieval per GB |
| --- | --- | --- | --- | --- | --- |
| S3 Standard | $0.005 | $0.0004 | n/a | n/a | n/a |
| S3 Intelligent-Tiering | $0.005 | $0.0004 | $0.01 | n/a | n/a |
| Intelligent-Tiering Archive Access, Expedited | n/a | n/a | n/a | $10.00 | $0.03 |
| S3 Standard-IA | $0.01 | $0.001 | $0.01 | n/a | $0.01 |
| S3 Glacier Instant Retrieval | $0.02 | $0.01 | $0.02 | n/a | $0.03 |
| S3 Glacier Flexible Retrieval | $0.03 | $0.0004 | $0.03 | see below | see below |
| Glacier Flexible, Expedited | n/a | n/a | n/a | $10.00 | $0.03 |
| Glacier Flexible, Standard | n/a | n/a | n/a | $0.05 | $0.01 |
| Glacier Flexible, Bulk | n/a | n/a | n/a | n/a | n/a ("Bulk data retrievals and requests are free of charge") |
| S3 Glacier Deep Archive | $0.05 | $0.0004 | $0.05 | see below | see below |
| Deep Archive, Standard | n/a | n/a | n/a | $0.10 | $0.02 |
| Deep Archive, Bulk | n/a | n/a | n/a | $0.025 | $0.0025 |
| S3 One Zone-IA | $0.01 | $0.001 | $0.01 | n/a | $0.01 |

Footnote: "S3 Intelligent-Tiering standard and bulk data retrieval and restore requests are free of charge for all five access tiers."

### Data transfer out to the internet

| Row | Price |
| --- | --- |
| Data transfer in | $0.00 per GB |
| First 10 TB / month (after 100 GB free across AWS) | $0.09 per GB |
| Next 40 TB / month | $0.085 per GB |
| Next 100 TB / month | $0.07 per GB |
| Greater than 150 TB / month | $0.05 per GB |

Units: "Amazon S3 storage usage is calculated in binary gigabytes (GB), where 1 GB is 2^30 bytes."

### AWS documentation

- Retrieval times (https://docs.aws.amazon.com/AmazonS3/latest/userguide/restoring-objects-retrieval-options.html): Glacier Flexible Retrieval Expedited 1-5 minutes, Standard 3-5 hours, Bulk 5-12 hours; Deep Archive Standard within 12 hours, Bulk within 48 hours. Glacier Instant Retrieval objects are "immediately available using GET".
- Storage classes (https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage-class-intro.html): minimum storage duration None / 30 / None (Intelligent-Tiering) / 90 / 90 / 180 days; minimum billable size None / 128 KB / None / 128 KB / NA / NA.
- Intelligent-Tiering (https://docs.aws.amazon.com/AmazonS3/latest/userguide/intelligent-tiering-overview.html): moves to Infrequent Access after 30 consecutive days without access and to Archive Instant Access after 90; optional Archive Access after at least 90 days and Deep Archive Access after at least 180 (each configurable up to 730); an accessed object returns to Frequent Access; objects under 128 KB are not monitored and stay in Frequent Access.

## Azure Blob Storage, East US 2, LRS, General Block Blob v2

Source: https://prices.azure.com/api/retail/prices (Azure Retail Prices API), filter serviceName 'Storage', armRegionName 'eastus2', productName 'General Block Blob v2', priceType 'Consumption'.

| SKU | Meter | Unit | Price |
| --- | --- | --- | --- |
| Hot LRS | Hot LRS Data Stored (0-50 TB) | 1 GB/Month | 0.0184 |
| Hot LRS | Hot LRS Data Stored (from 50 TB) | 1 GB/Month | 0.017664 |
| Hot LRS | Hot LRS Data Stored (from 500 TB) | 1 GB/Month | 0.016928 |
| Hot LRS | Hot LRS Write Operations | 10K | 0.05 |
| Hot LRS | Hot Read Operations | 10K | 0.004 |
| Cool LRS | Cool LRS Data Stored | 1 GB/Month | 0.01 |
| Cool LRS | Cool Data Retrieval | 1 GB | 0.01 |
| Cool LRS | Cool LRS Write Operations | 10K | 0.1 |
| Cool LRS | Cool Read Operations | 10K | 0.01 |
| Cool LRS | Cool LRS Early Delete | 1 GB | 0.01 |
| Cold LRS | Cold LRS Data Stored | 1 GB/Month | 0.0036 |
| Cold LRS | Cold LRS Data Retrieval | 1 GB | 0.03 |
| Cold LRS | Cold LRS Write Operations | 10K | 0.18 |
| Cold LRS | Cold LRS Read Operations | 10K | 0.1 |
| Cold LRS | Cold LRS Early Delete | 1 GB | 0.0036 |
| Archive LRS | Archive LRS Data Stored | 1 GB/Month | 0.002 |
| Archive LRS | Archive Data Retrieval | 1 GB | 0.02 |
| Archive LRS | Archive Priority Data Retrieval | 1 GB | 0.1 |
| Archive LRS | Archive LRS Write Operations | 10K | 0.1 |
| Archive LRS | Archive Read Operations | 10K | 5 |
| Archive LRS | Archive Priority Read Operations | 10K | 50 |
| Archive LRS | Archive LRS Early Delete | 1 GB | 0.002 |

Bandwidth API (serviceName 'Bandwidth', eastus2): Standard Data Transfer Out, Microsoft global network routing: 0 for the first 100 GB, then $0.087 per GB, $0.083 from 10 TB, $0.07 from 50 TB, $0.05 from 150 TB.

Microsoft Learn, access tiers (https://learn.microsoft.com/en-us/azure/storage/blobs/access-tiers-overview): minimum retention Cool 30 days, Cold 90 days, Archive 180 days; latency Hot, Cool and Cold "Milliseconds", Archive "Hours"; "Data in the archive tier can take up to 15 hours to rehydrate". No minimum billable object size is listed there or on the pricing page (https://azure.microsoft.com/en-us/pricing/details/storage/blobs/); the only 128 KiB rule on the pricing page is the smart-tier monitoring charge ("for each set of 10 000 objects over 128KiB"), and smart tier "is available for redundancies ZRS, GZRS and RA-GZRS".

## Google Cloud Storage, us-central1 (Iowa)

Source: https://cloud.google.com/storage/pricing.

| Item | Listed price | Monthly (x 730 hours) |
| --- | --- | --- |
| Standard storage | $0.000027397 per GiB-hour | $0.0200 per GiB |
| Nearline storage | $0.000013699 per GiB-hour | $0.0100 per GiB |
| Coldline storage | $0.000005479 per GiB-hour | $0.0040 per GiB |
| Archive storage | $0.000001644 per GiB-hour | $0.0012 per GiB |

Operations, "for buckets located in a single region", flat namespace (per 1,000): Class A Standard $0.005, Nearline $0.01, Coldline $0.02, Archive $0.05; Class B Standard $0.0004, Nearline $0.001, Coldline $0.01, Archive $0.05.

Retrieval: Standard $0, Nearline $0.01, Coldline $0.02, Archive $0.05 per GiB. Minimum storage duration: Standard none, Nearline 30 days, Coldline 90 days, Archive 365 days. Internet egress to worldwide destinations (excluding Asia and Australia): $0.12 per GiB for 0-10 TiB. Autoclass management fee: "$0.0025 for every 1000 objects stored for 30 days".

Docs: storage classes (https://docs.cloud.google.com/storage/docs/storage-classes): "No minimum object size"; data "available within milliseconds, not hours or days". Autoclass (https://docs.cloud.google.com/storage/docs/autoclass): to Nearline after 30 days without access, Coldline after 90, Archive after 365 (Archive terminal class only); objects under 128 KiB do not move; no retrieval or early-deletion fees except at enablement.

## Phase 3 additions (read 2026-10-30)

The billing *rules* (proration, early deletion, restores, moves, the rivals) are quoted with their sources in `docs/SIM_RULES.md`. New price-sheet values from that reading:

- Azure, archived blob metadata (https://learn.microsoft.com/en-us/azure/storage/common/storage-plan-manage-costs): "The metadata that is associated with blobs in the archive tier is stored separately in the cold tier ... Because the size of metadata doesn't exceed 8 KB in size, its cost is relatively insignificant." The access-tiers page says: "Storage costs for metadata of archived blobs will be charged on cool tier rates." Sheet: 8 KB at the cool rate (D-026).
- Azure, high-priority rehydration (https://learn.microsoft.com/en-us/azure/storage/blobs/archive-rehydrate-overview): "might complete in less than one hour for objects under 10 GB in size". Sheet: 1 hour.
- Azure units (pricing page): "Azure Blob Storage usage is calculated in binary Gigabytes (GB), where 1 GB = 2^30 bytes."
- AWS lower ends of restore ranges (retrieval-options page): Flexible standard 3 h, bulk 5 h, expedited 1 minute. Intelligent-Tiering Archive Access "can range from 3-5 hours"; Deep Archive Access "within 12 hours".

## Phase 4 additions (read 2026-10-30): policy rules

These decide which plans a customer could actually run, not prices. Used by `src/sat/policies/rules.py` and the Azure rival.

- AWS lifecycle transitions (https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-transition-general-considerations.html): "Objects smaller than 128 KB will not transition by default to any storage class". "Starting September 2024, the default behavior prevents objects smaller than 128 KB from being transitioned to any storage class." "You can't create a single Lifecycle rule that transitions objects from one storage class to another before the minimum storage duration period has passed." Policies keep objects under 128 KB in Standard on AWS (D-033).
- AWS lifecycle configuration elements (https://docs.aws.amazon.com/AmazonS3/latest/userguide/intro-lifecycle-rules.html): "By default, objects smaller than 128 KB will not be transitioned to any storage class, unless you specify a smaller minimum size (ObjectSizeGreaterThan)". We keep the default.
- AWS managing Intelligent-Tiering (https://docs.aws.amazon.com/AmazonS3/latest/userguide/intelligent-tiering-managing.html): "When you restore an object from the Archive Access tier or Deep Archive Access tier, the object moves back into the Frequent Access tier. Afterwards, if the object isn't accessed for 30 consecutive days, it automatically moves into the Infrequent Access tier." Basis of the forecast-restore policy (D-034, assumption A11).
- Azure lifecycle policy structure (https://learn.microsoft.com/en-us/azure/storage/blobs/lifecycle-management-policy-structure): `enableAutoTierToHotFromCool`: "If a blob is set to the cool tier, this action automatically moves that blob into the hot tier when the blob is accessed." "This action is available only when used with the daysAfterLastAccessTimeGreaterThan run condition." "This action moves blobs from cool to hot only one time in 30 days."
- Azure lifecycle overview (https://learn.microsoft.com/en-us/azure/storage/blobs/lifecycle-management-overview): "Each last access time update is charged as an "other transaction" at most once every 24 hours per object even if it's accessed thousands of times in a day."
- Azure Retail Prices API, product "General Block Blob v2", eastus2, meter "All Other Operations": `retailPrice` 0.004, `unitOfMeasure` "10K" (Hot tier). Sheet: `extras.other_operations_per_1000` = 0.0004.

