# Phase 2 quality report

## D1: PASS

| Check | Result | Detail |
| --- | --- | --- |
| date range complete | pass | 2016-01-01 .. 2025-12-31, expected 2016-01-01 .. 2025-12-31 |
| rows = items x days | pass | 36,530,000 rows; 10,000 items x 3,653 days = 36,530,000 |
| no duplicate (item, date) | pass | unique pairs equal rows |
| no negative counts | pass | min 0 |
| every listed item downloaded | pass | 10,000 in data, 10000 listed |
| not mostly empty | pass | 74.0% of cells above zero |
| flags computed (informational) | pass | 10,000 items; bursty 1,054, thin 1,189 |
| manifest checksums match | pass | 84 files re-checked, 0 without stored path |

## D2: PASS

| Check | Result | Detail |
| --- | --- | --- |
| size distribution measured | pass | median bytes about 24547.089156850285 |
| manifest checksums match | pass | 1 files re-checked, 0 without stored path |

## D3: PASS

| Check | Result | Detail |
| --- | --- | --- |
| date range complete | pass | 2016-01-01 .. 2025-12-31, expected 2016-01-01 .. 2025-12-31 |
| rows = items x days | pass | 1,095,900 rows; 300 items x 3,653 days = 1,095,900 |
| no duplicate (item, date) | pass | unique pairs equal rows |
| no negative counts | pass | min 0 |
| every listed item downloaded | pass | 300 in data, 300 listed |
| not mostly empty | pass | 79.6% of cells above zero |
| flags computed (informational) | pass | 300 items; bursty 16, thin 43 |
| manifest checksums match | pass | 3 files re-checked, 0 without stored path |

## D4: PASS

| Check | Result | Detail |
| --- | --- | --- |
| every year matches the server row count | pass | 51,804,190 rows in 22 years |
| manifest checksums match | pass | 1045 files re-checked, 0 without stored path |

## D5: PASS

| Check | Result | Detail |
| --- | --- | --- |
| size distribution measured | pass | median bytes about 58884.36553555884 |
| manifest checksums match | pass | 2 files re-checked, 0 without stored path |
