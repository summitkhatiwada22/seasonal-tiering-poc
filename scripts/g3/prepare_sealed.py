# ruff: noqa: E501, B023
"""Prepare the sealed-year files for the G3 run (data preparation only; no analysis).

1. Copy the sealed partitions staged from the owner's flash drive into the workspace:
   D1 and D3 views for 2024 and 2025 into data/processed; the full D4 checkouts for 2023 to 2025
   into data/interim/D4_full (2023 only to prove the extraction below matches the pre-freeze one).
2. Record size, SHA-256 and the flash drive's modification time of every copied file in
   reports/g3/sealed_files.csv, with the time the freeze tag was published.
3. Unlock the sealed years from the tagged commit and extract the D4 sample (D-030: monthly
   checkouts of the 10,000 fixed sample keys) for 2024 and 2025 with the frozen helpers of
   sat.data.d4_sample. The same code is first run on 2023 and must reproduce the 2023 partition
   built before the freeze exactly.
"""

import csv
import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from sat.data import d4_sample as d4
from sat.data.sealed import unlock_sealed, year_partitions

REPO = Path("/home/claude/seasonal-tiering-poc")
STAGED = Path("/mnt/user-data/uploads/FLASH--seasonal-tiering-data/processed")
DEVICE = "/Volumes/FLASH/seasonal-tiering-data/processed"
MTIME_MS = {  # from the device listing / staging results, 2026-10-30
    "D1/year=2024/views.parquet": 1793268686536,
    "D1/year=2025/views.parquet": 1793268699194,
    "D3/year=2024/views.parquet": 1793269698329,
    "D3/year=2025/views.parquet": 1793269698356,
    "D4/year=2023/checkouts.parquet": 1793291376470,
    "D4/year=2024/checkouts.parquet": 1793291406896,
    "D4/year=2025/checkouts.parquet": 1793291442434,
}
TAG_PUBLISHED = datetime(2026, 10, 30, 16, 32, 32, tzinfo=UTC)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


rows = []
for rel, ms in MTIME_MS.items():
    src = STAGED / rel
    ds = rel.split("/")[0]
    dst = (
        (REPO / "data" / "interim" / "D4_full" / Path(rel).relative_to("D4"))
        if ds == "D4"
        else (REPO / "data" / "processed" / rel)
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not (dst.exists() and dst.resolve() == src.resolve()):  # D1, D3: data/processed links here
        shutil.copyfile(src, dst)
    mtime = datetime.fromtimestamp(ms / 1000, tz=UTC)
    rows.append(
        {
            "device_path": f"{DEVICE}/{rel}",
            "workspace_path": str(dst.relative_to(REPO)),
            "bytes": dst.stat().st_size,
            "sha256": sha(dst),
            "device_mtime_utc": mtime.isoformat(),
            "before_freeze_tag": mtime < TAG_PUBLISHED,
        }
    )
    assert sha(src) == rows[-1]["sha256"]

print("unlocked at", unlock_sealed(REPO))
keys = pl.read_parquet(REPO / "data" / "processed" / "D4_sample" / "keys.parquet")
root = REPO / "data" / "interim" / "D4_full"
for year in (2023, 2024, 2025):
    (part,) = year_partitions(root, [year], max_year=2025)
    monthly = (
        d4._keyed(part)
        .join(keys.lazy(), on=d4.KEY, how="inner")
        .group_by("key_id", "year", "month")
        .agg(pl.col("checkouts").sum())
        .collect()
        .sort("key_id", "year", "month")
    )
    target = REPO / "data" / "processed" / "D4_sample" / f"year={year}" / "monthly.parquet"
    if year == 2023:
        before = pl.read_parquet(target).sort("key_id", "year", "month")
        same = before.select(sorted(before.columns)).equals(
            monthly.cast(before.schema).select(sorted(before.columns))
        )
        print(
            "2023 extraction equals the pre-freeze partition:", same, monthly.height, before.height
        )
        assert same
        continue
    monthly = monthly.cast(
        dict(pl.read_parquet(REPO / "data/processed/D4_sample/year=2023/monthly.parquet").schema)
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    monthly.write_parquet(target)
    rows.append(
        {
            "device_path": f"derived from {DEVICE}/D4/year={year}/checkouts.parquet (D-030 sample)",
            "workspace_path": str(target.relative_to(REPO)),
            "bytes": target.stat().st_size,
            "sha256": sha(target),
            "device_mtime_utc": "",
            "before_freeze_tag": "",
        }
    )
    print(year, "sample rows", monthly.height, "checkouts", int(monthly["checkouts"].sum()))

out = REPO / "reports" / "g3"
out.mkdir(parents=True, exist_ok=True)
with (out / "sealed_files.csv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(open(out / "sealed_files.csv").read())
