# manifests/

One CSV per dataset (from Phase 2), recording every raw file we used. This is what lets a stranger download the same files and verify they are testing the same data.

Columns:

| Column | Meaning |
| --- | --- |
| `dataset` | Dataset id, for example `D2` |
| `url` | Where the file came from |
| `sha256` | SHA-256 checksum, a fingerprint of the file's bytes |
| `bytes` | File size |
| `downloaded_utc` | When we fetched it |

Raw files themselves are never committed.
