# Azure ZRS and smart tier prices, read 2026-10-30

Read from the Azure Retail Prices API (https://prices.azure.com/api/retail/prices) in the built-in browser, because the build workspace cannot reach it. Region `eastus2`, `priceType eq 'Consumption'`. Columns: skuName | meterName | retailPrice | unitOfMeasure | tierMinimumUnits | effectiveStartDate. Only the rows the ZRS sheet uses are copied; the query returned 68 rows for `productName eq 'General Block Blob v2' and contains(skuName,'ZRS')`.

```
Hot ZRS  | Hot ZRS Data Stored        | 0.023   | 1 GB/Month | 0      | 2018-06-01
Hot ZRS  | Hot ZRS Data Stored        | 0.02208 | 1 GB/Month | 51200  | 2018-06-01
Hot ZRS  | Hot ZRS Data Stored        | 0.02116 | 1 GB/Month | 512000 | 2018-06-01
Hot ZRS  | Hot ZRS Write Operations   | 0.0625  | 10K        | 0      | 2018-06-01
Hot ZRS  | Hot ZRS Read Operations    | 0.004   | 10K        | 0      | 2018-06-01
Hot ZRS  | All Other Operations       | 0.004   | 10K        | 0      | 2017-10-01
Cool ZRS | Cool ZRS Data Stored       | 0.0125  | 1 GB/Month | 0      | 2018-06-01
Cool ZRS | Cool ZRS Write Operations  | 0.1     | 10K        | 0      | 2018-06-01
Cool ZRS | Cool ZRS Read Operations   | 0.01    | 10K        | 0      | 2018-06-01
Cool ZRS | Cool ZRS Data Retrieval    | 0.01    | 1 GB       | 0      | 2018-06-01
Cool ZRS | Cool ZRS Early Delete      | 0.0125  | 1 GB       | 0      | 2018-06-01
Cold ZRS | Cold ZRS Data Stored       | 0.004   | 1 GB/Month | 0      | 2023-05-01
Cold ZRS | Cold ZRS Write Operations  | 0.2     | 10K        | 0      | 2023-05-01
Cold ZRS | Cold ZRS Read Operations   | 0.1     | 10K        | 0      | 2023-05-01
Cold ZRS | Cold ZRS Data Retrieval    | 0.03    | 1 GB       | 0      | 2023-05-01
Cold ZRS | Cold ZRS Early Delete      | 0.004   | 1 GB       | 0      | 2023-05-01
```

Smart tier (`contains(meterName,'Smart')`, product "Blob Features"):

```
Smart Tier ZRS    | Smart Tier ZRS Monitoring Operations    | 0.04 | 10K | 2026-05-01
Smart Tier GZRS   | Smart Tier GZRS Monitoring Operations   | 0.04 | 10K | 2026-05-01
Smart Tier RA-GZRS| Smart Tier RA-GZRS Monitoring Operations| 0.04 | 10K | 2026-05-01
```

Rules, from Microsoft Learn ("Smart tier", access-tiers-smart): new data in hot; "Any object that isn't accessed for 30 days is moved to the cool tier"; "After 60 more days without accessing objects on smart tier, they transition to the cold tier"; Get Blob and Put Blob are access operations and "immediately move the object to hot tier"; no charges for tier transitions, early deletion or data retrieval; access operations "billed against hot tier rates"; objects below 128 KiB stay in hot without a monitoring fee; "a monthly monitoring operation for each object over 128 KiB"; requires ZRS, GZRS or RA-GZRS. Access tiers overview: "The archive tier isn't supported for ZRS, GZRS, or RA-GZRS accounts."
