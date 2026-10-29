# data_records/manifests/

One CSV per dataset (D1 to D5, from Phase 2), recording every raw file we used. This is what lets a stranger download the same files and verify they are testing the same data.

Columns:

| Column | Meaning |
| --- | --- |
| `dataset` | Dataset id, for example `D2` |
| `url` | Where the file came from |
| `sha256` | SHA-256 checksum, a fingerprint of the file's bytes |
| `bytes` | File size |
| `downloaded_utc` | When we fetched it |
| `path` | The file's location inside the data folder, so checksums can be re-verified (`sat.ingest.quality` does this) |

Raw files themselves are never committed. They live in the owner's data folder (currently a flash drive); the other small records (article and package lists, flags, size summaries, the quality report) are one folder up in `data_records/`.
