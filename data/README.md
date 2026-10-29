# data/

Local data only. Everything under `raw/`, `interim/` and `processed/` is git-ignored and never committed.

| Folder | Holds |
| --- | --- |
| `raw/` | Files exactly as downloaded. Deleted after conversion once the checksum is recorded in `manifests/` |
| `interim/` | Temporary working files |
| `processed/` | Parquet tables the simulator reads, plus synthetic data |

Anyone can rebuild all of it with `make data` (Phase 2 onward) from the manifests.
