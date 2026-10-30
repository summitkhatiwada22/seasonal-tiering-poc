# Storage policies (Phase 4)

A **policy** decides, every day and for every object, which storage class the object sits in, and (for archive classes) when to ask for a restored copy. The simulator (`src/sat/sim/`, rules in [SIM_RULES.md](SIM_RULES.md)) then bills the plan and measures how long reads wait.

All settings below are fixed in `src/sat/policies/grid.py` before any real-data run (decisions D-033 and D-034). Each family picks its best setting on 2022 by the same rule ([E1_PROTOCOL.md](E1_PROTOCOL.md)).

## Roles

| Role | Families | Meaning |
| --- | --- | --- |
| **Rival** | `lifecycle`, `managed`, `access-lifecycle` | What a customer can switch on today without any forecast |
| **Ours** | `seasonal` | Seasonal-naive forecasting: "the coming days will look like the same days last year" |
| Reference | `reactive` | Our policy with the seasonal part switched off. If ours beats the rival but not this, the gain comes from reacting to reads, not from seasonality |
| Reference | `oracle` | Our policy fed the true future reads. It cannot be run in practice; it shows the most any forecast could add |

Only rivals and `seasonal` are compared in the E1 decision. The references are reported next to them.

## Rivals

| Policy | Clouds | Settings | What it does |
| --- | --- | --- | --- |
| `all-<first class>` | all | none | Everything stays in Standard (AWS, Google) or Hot (Azure) |
| `lifecycle:<class>@<N>d` | all | every other class; N = 30 or 90 days after upload | Age-based rule with one transition. For objects stored long before the window this is the same as keeping everything in that class |
| `intelligent-tiering[...]` | AWS | archive tiers off; Archive Access after 90 or 180 days; Deep Archive Access after 180 days alone; both at 90 and 180, or at 90 and 365 | S3 Intelligent-Tiering, billed by the simulator's managed-class rules (I1 to I4) |
| `autoclass:<terminal>` | Google | terminal class Nearline (default) or Archive | Google Autoclass, rules I1 to I4 |
| `azure-last-access:...` | Azure | cool after 30 days without access; plus cold after 90; plus archive after 180; cool 90 and cold 180; cool 30 and archive 180 | Azure lifecycle rules on `daysAfterLastAccessTimeGreaterThan` with `enableAutoTierToHotFromCool` (a read returns a cool blob to hot, at most once in 30 days; cold and archive blobs never return by themselves). Pays last-access tracking: one "other operation" per object per day with a read. Stands in for Azure smart tier, which has no price for LRS storage |

## Ours, and its references

All three forms below exist in `seasonal`, `reactive` and `oracle` versions that differ **only in the forecast**:

| Forecast | Expected reads in the next days |
| --- | --- |
| `seasonal` | The same days last year (364 days back, so weekdays line up), or the recent past if that was busier. The second part stops an object that did not exist, or was quiet, a year ago from being forecast as unread while it is being read |
| `reactive` | The recent past only |
| `oracle` | The true future |

Every forecast uses only reads before the day it decides, except the oracle. A test checks this for every policy: changing reads on or after a day never changes the plan before it.

### 1. Warm/cold rule (`TwoTier`)

Two classes, a warm one and a cold one.

- **Warm** when a read is expected within `lead` days (7 or 30) or the object was read in the last `recency` days (7, 30 or 90).
- **Cold** only when no read is expected for the cold class's whole minimum storage duration, and the object has spent the warm class's minimum duration warm.

Two ways to warm an archived object:
- **move:** restore it and copy it into the warm class.
- **copy:** leave it archived and ask for a temporary restored copy covering the expected reads.

Class pairs:
- AWS: Standard with Standard-IA, Glacier Instant, Glacier Flexible or Deep Archive; Glacier Instant with Glacier Flexible or Deep Archive.
- Google: Standard with Nearline, Coldline or Archive; Nearline with Archive.
- Azure: Hot with Cool, Cold or Archive; Cool with Archive.

This rule ignores fees. On synthetic data it lost even to its own reactive copy (D-034). It is kept so the record shows that.

### 2. Fee-aware planner (`Planner`)

The planner looks ahead `H` days (30, 90 or 180). Every day, for every object, it estimates the cost per day of each allowed class given the forecast:
- **Storage**, including the minimum billable size and the per-object archive overhead.
- **Reads**, including retrieval fees, or a restore for an archive class.
- **Moving there now**, a one-off cost: the transition fee, or a restore and copy, plus early deletion of the class being left. It is spread over the longer of the horizon and the new class's minimum duration.

The planner picks the cheapest class. An archive class is not allowed while a read is expected within `lead` days (7 or 30), so the object is warmed in time. The estimate only guides the choice; the simulator bills the plan exactly.

Class sets:
- AWS: Standard to Glacier Instant; Standard, Glacier Instant and Deep Archive; all five classes.
- Google: Standard to Coldline; all four.
- Azure: Hot to Cold; all four.

### 3. Intelligent-Tiering with forecast restores (`ITPrewarm`, AWS only)

Objects live in S3 Intelligent-Tiering with its archive tiers on: Archive Access after 90 days, with or without Deep Archive Access after 180. When the forecast expects a read within `lead` days (7 or 30), the policy restores the object in advance. AWS states that a restored object "moves back into the Frequent Access tier" (assumption A11). The managed service still does all the cost-saving moves for free; the forecast only removes the wait. There is no reactive form, because plain Intelligent-Tiering is the reactive form.

## Costs every one of our policies pays

- **Knowing the reads (assumption A12).** On Azure, last-access tracking. On AWS and Google, server access logs stored in Standard. The rivals that do not need this (managed services, age rules) do not pay it.
- **Small objects on AWS.** Objects under 128 KB never leave Standard, the AWS lifecycle default since September 2024. A rule check (`src/sat/policies/rules.py`) refuses any AWS plan that breaks it or moves an object up the waterfall without a restore.

## Number of settings per cloud

| Cloud | Rivals | Ours (`seasonal`) | `reactive` | `oracle` |
| --- | --- | --- | --- | --- |
| AWS | 15 | 67 | 39 | 19 |
| Google | 9 | 30 | 18 | 10 |
| Azure | 12 | 39 | 24 | 11 |

Ours has more settings than the rivals because it has more knobs. Picking on 2022 and scoring once on 2023 keeps the extra choice from turning into an advantage.
