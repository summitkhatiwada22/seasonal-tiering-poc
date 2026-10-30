# Hand calculations for Gate G2

Each case is worked out with plain arithmetic from the official prices (`docs/evidence/official-prices-2026-10-30.md`) and rules (`docs/SIM_RULES.md`). Cases H01 to H18 were written **before** the simulator code existed. H19 to H24 were added after the deliberate-bug check (below) showed three rules, and later the creation-day rules, were not yet pinned down by a test. The tests in `tests/test_sim_hand.py` hold these numbers as literals and require the simulator to match each to a relative error of 1e-9.

Conventions: 1 GiB = 2^30 bytes; 1 KiB = 1/1,048,576 GiB. All cases start on 2023-01-01, a training-period date (any calendar would do). "Hour *h*" counts from 00:00 on day 0. Google's daily rate = monthly sheet value x 24 / 730.

## Storage

| # | Case | Arithmetic | Expected (USD) |
| --- | --- | --- | --- |
| H01 | AWS Standard, 1 GiB, all of January (31 days) | 31 x 0.023 / 31 | 0.023 |
| H02 | AWS Standard, 1 GiB, 15 days of January; and all 28 days of February | 0.023 x 15 / 31; 0.023 x 28 / 28 | 0.01112903...; 0.023 |
| H03 | AWS Deep Archive, 1 GiB, Jan to Mar (90 days) | storage 3 x 0.00099; overhead 3 x (32 KiB x 0.00099 + 8 KiB x 0.023) | 0.00297; 0.000000617... |
| H09 | AWS Standard-IA, one 10 KiB object, January | billed as 128 KiB: 128 KiB x 0.0125 | 0.00000152... |

## Moves between classes

| # | Case | Arithmetic | Expected |
| --- | --- | --- | --- |
| H04 | AWS: 1,000 objects of 1 MiB, Standard days 0-9, lifecycle to Glacier Flexible on day 10 | transition 1,000 x 0.03 / 1,000; storage (1,000/1,024 GiB) x (0.023 x 10/31 + 0.0036 x 21/31); overhead 1,000 x (32 KiB x 0.0036 + 8 KiB x 0.023) x 21/31 | transition 0.03 |
| H05 | AWS: 1 GiB enters Glacier Flexible on day 0, lifecycle to Deep Archive on day 30 (Jan 31) | early deletion (90 - 30) days x 0.0036 x (1 GiB + 32 KiB) / 31; transition 0.05 / 1,000 | 0.006968... ; 0.00005 |
| H12 | Google, Google's own example: created Nearline, lifecycle to Coldline day 20, rewritten to Standard day 80 | lifecycle: Class A Coldline 0.02/1,000, no early deletion, clock keeps running; rewrite at age 80 < 90: early deletion 10 days x 0.004 x 24/730, retrieval 0.02, Class A Standard 0.005/1,000 | early deletion 0.001315... |
| H13 | Azure, Microsoft's own example: 1,000 GB archived 90 days, rehydrated to Hot, read once | retrieval 0.02 x 1,000 = 20; rehydrate read op 5/10,000 = 0.0005; early deletion (180 - 90)/30 x 0.002 x 1,000 = 6; Hot read 0.004/10,000 | **26.0005004** (Microsoft's figure: "$26") |
| H14 | Azure: Cool on day 0, moved to Hot on day 21 (Microsoft's 21-day example) | early deletion (30 - 21)/30 x 0.01; Cool read op 0.01/10,000; retrieval 0.01 | 0.003 |

## Reads, restores and waits

| # | Case | Arithmetic | Expected |
| --- | --- | --- | --- |
| H06 | AWS Glacier Flexible, 1 GiB, read once on day 5, nothing pre-warmed | restore 0.05/1,000; retrieval 0.01; copy ready hour 125, expires next midnight after 125 + 24 = 149, i.e. 168: 43 hours x 0.023 / (24 x 31); GET 0.0004/1,000. Wait 5 h (3 h at the low end, copy 45 h) | wait 5 h |
| H07 | Same, pre-warmed on day 3 for 7 days; reads day 5 (1) and day 12 (2) | copy ready 77, expires 264 (day 11): 187 h; day 5 read instant; day 12 after expiry: on-demand restore, ready 293, expires 336: 43 h. Two restores, three GETs; 2 reads wait 5 h each (first-read total 5 h) | waits 10 h / 5 h |
| H08 | AWS Glacier Instant, 1 GiB, 10 reads on one day | GET 10 x 0.01/1,000; retrieval 10 x 0.03 | 0.3001 |
| H10 | AWS Deep Archive, bulk restore day 1 for 3 days; read day 2 | ready 24 + 48 = 72, expires 144: 72 h copy; fee 0.025/1,000 + 0.0025; read at hour 48 waits 24 h | wait 24 h |
| H11 | Google Coldline, 1 GiB, January, 3 reads on day 10 | storage 31 x 0.004 x 24/730; Class B 3 x 0.01/1,000; retrieval 3 x 0.02 | retrieval 0.06 |
| H15 | Azure Archive, copy to Hot on day 2 for 2 days, read day 3 | ready 48 + 15 = 63, expires 120: 57 h x 0.0184 / (24 x 31); archive read op 5/10,000 + Hot write 0.05/10,000; retrieval 0.02; Hot read 0.004/10,000; archive metadata 8 KiB x 0.01 | no wait |
| H19 | AWS: pre-warm day 3 for 7 days; read on day 11 (the expiry midnight) | copy gone at hour 264 = day 11 00:00: a second restore and a wait | 2 restores |
| H20 | AWS: restore day 3 for 2 days, asked again day 5 for 5 days | first copy 77 -> 144 (67 h); second request while active: one GET (0.0004/1,000), expiry 120 + 120 = 240 (+96 h) | copy 163 h |

## The rivals

| # | Case | Arithmetic | Expected |
| --- | --- | --- | --- |
| H16 | S3 Intelligent-Tiering, 1 GiB, never read until day 100 (Apr 11) | Frequent days 0-29: 30 x 0.023/31; Infrequent day 30 (Jan 31) 0.0125/31 + Feb 0.0125 + Mar 0.0125; Archive Instant Apr 1-11: 11 x 0.004/30; monitoring 0.0025/1,000 x (3 + 11/30); GET 0.0004/1,000; no retrieval | as stated |
| H18 | Intelligent-Tiering with Archive Access at 90 days, read on day 95 | free restore, wait 5 h (3 h low); Archive Access days 90-95: overhead 6/30 x (32 KiB x 0.0036 + 8 KiB x 0.023) | wait 5 h |
| H17 | Autoclass (Archive terminal), 1 GiB, read on day 100 | Standard 30 days, Nearline 60, Coldline 11: (30 x 0.02 + 60 x 0.01 + 11 x 0.004) x 24/730; Coldline -> Standard: one Class A at the Standard rate 0.005/1,000; Class B at the Standard rate; fee 101 x 0.0025/1,000/30 | transition 0.000005 |
| H21 | Autoclass, read on day 40 (in Nearline) | Nearline -> Standard is free | transition 0 |

## Objects created during the period

| # | Case | Arithmetic | Expected |
| --- | --- | --- | --- |
| H22 | AWS: uploaded day 10 into Standard-IA, copied to Standard day 20 | PUT IA 0.01/1,000; early deletion (30 - 10) x 0.0125/31; COPY 0.005/1,000; retrieval 0.01; storage 10 x 0.0125/31 + 11 x 0.023/31 | early deletion 0.008064... |
| H23 | Intelligent-Tiering object uploaded day 5 | Frequent Jan 6-31 (26 d) and Feb 1-4 (4 d), Infrequent Feb 5-9 (5 d); monitoring for 26/31 + 9/28 months; PUT 0.005/1,000 | as stated |
| H24 | Plan changes before the object exists (upload day 10 into Glacier Flexible) | no transition; one PUT 0.03/1,000; 21 days x 0.0036/31 | transition 0 |

## Check of the checks

`scripts/mutation_check.py` plants 22 deliberate bugs in the simulator, one at a time (for example decimal instead of binary GB, early deletion always over 30 days, a copy still readable at its expiry hour, Autoclass charging for Nearline -> Standard). On the first run 16 of 19 were caught; the three misses led to H19, H20 and H21, and the creation-day bugs to H24. Final run: **22 of 22 caught**.
