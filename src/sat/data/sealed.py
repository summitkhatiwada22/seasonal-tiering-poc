"""The lock on the sealed test years.

2024 and later are the sealed test (D1 and D3: 2024-2025; D4: 2024 to 2026-09). Nothing may read
them before the Phase 6 freeze, so every loader asks this module which yearly partition files it
may open. The check works on the ``year=YYYY`` folder names *before* any file is opened, so a
sealed file is never read, not even to be filtered afterwards.

There is deliberately no way to unlock the sealed years here. Phase 6 adds the unlock, tied to the
freeze tag that records the pre-registered thresholds.

``max_year`` adds a second, temporary lock: while tuning on 2022 the loaders run with
``max_year=2022`` so the 2023 validation year is not read either.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

SEALED_FROM_YEAR = 2024
VALIDATION_YEAR = 2023
TUNING_YEAR = 2022
FIRST_YEAR = 2016

_PARTITION = re.compile(r"^year=(\d{4})$")


class SealedYearError(PermissionError):
    """Raised on any attempt to read a sealed (2024+) or locked year."""


def check_year(year: int, max_year: int) -> None:
    if year >= SEALED_FROM_YEAR:
        raise SealedYearError(
            f"{year} is a sealed test year (>= {SEALED_FROM_YEAR}); it unlocks only after the "
            "Phase 6 freeze"
        )
    if max_year >= SEALED_FROM_YEAR:
        raise SealedYearError(f"max_year {max_year} reaches into the sealed years")
    if year > max_year:
        raise SealedYearError(f"{year} is locked for this run (max_year={max_year})")


def year_partitions(dataset_dir: Path, years: Iterable[int], max_year: int) -> list[Path]:
    """Folders ``dataset_dir/year=YYYY`` for the requested years, refusing sealed or locked ones.

    Only folder names are inspected; nothing inside a refused folder is touched.
    """
    wanted = sorted(set(years))
    for year in wanted:
        check_year(year, max_year)
    present = {}
    for child in dataset_dir.iterdir():
        match = _PARTITION.match(child.name)
        if match and child.is_dir():
            present[int(match.group(1))] = child
    missing = [y for y in wanted if y not in present]
    if missing:
        raise FileNotFoundError(f"{dataset_dir}: no partition for years {missing}")
    return [present[y] for y in wanted]
