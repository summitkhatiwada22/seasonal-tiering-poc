# data/

Local data only. Everything under `raw/`, `interim/` and `processed/` is git-ignored and never committed.

| Folder | Holds |
| --- | --- |
| `raw/` | Files exactly as downloaded, with checksums recorded in `data_records/manifests/` |
| `interim/` | Temporary working files |
| `processed/` | Parquet tables the simulator reads, plus synthetic data |

The real datasets are large, so Phase 2 stores them outside the repository (the owner's flash drive). `docs/RUNBOOK_PHASE2.md` lists the commands that rebuild them; `make data` prints the pointer. The folders here hold only small synthetic data.
