"""The lock on the sealed test years.

2024 and later are the sealed test (D1 and D3: 2024-2025; D4: 2024 to 2026-09). Nothing may read
them before the Phase 6 freeze, so every loader asks this module which yearly partition files it
may open. The check works on the ``year=YYYY`` folder names *before* any file is opened, so a
sealed file is never read, not even to be filtered afterwards.

The only way to unlock them is ``unlock_sealed`` (Phase 6, docs/PREREGISTRATION.md). It succeeds
only when the code running is exactly the commit the freeze tag ``freeze-g3`` points to, on GitHub
and locally, with no tracked file changed. The tag is created by the owner on GitHub after the
pre-registration is pushed, so the sealed years can only be read by code fixed before they were.

``max_year`` adds a second, temporary lock: while tuning on 2022 the loaders run with
``max_year=2022`` so the 2023 validation year is not read either.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

SEALED_FROM_YEAR = 2024
VALIDATION_YEAR = 2023
TUNING_YEAR = 2022
FIRST_YEAR = 2016

FREEZE_TAG = "freeze-g3"

_PARTITION = re.compile(r"^year=(\d{4})$")
_unlocked_at: str | None = None  # the freeze commit, once unlocked in this process


class SealedYearError(PermissionError):
    """Raised on any attempt to read a sealed (2024+) or locked year."""


def unlock_sealed(repo: Path, tag: str = FREEZE_TAG) -> str:
    """Unlock 2024 and later for this process, for the one sealed run. Returns the freeze commit.

    Refused unless the tag exists on ``origin``, the local tag names the same commit, HEAD is that
    commit, and no tracked file differs from it (untracked outputs are allowed)."""
    global _unlocked_at

    def git(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
        if done.returncode != 0:
            raise SealedYearError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
        return done.stdout.strip()

    remote: dict[str, str] = {}
    for line in git("ls-remote", "--tags", "origin", f"refs/tags/{tag}*").splitlines():
        sha, ref = line.split()
        remote[ref] = sha
    on_origin = remote.get(f"refs/tags/{tag}^{{}}") or remote.get(f"refs/tags/{tag}")
    if not on_origin:
        raise SealedYearError(f"tag {tag!r} is not on origin: create it on GitHub first")
    try:
        local = git("rev-parse", f"{tag}^{{commit}}")
    except SealedYearError as exc:
        raise SealedYearError(f"tag {tag!r} is not fetched here: run git fetch --tags") from exc
    head = git("rev-parse", "HEAD")
    if not on_origin == local == head:
        raise SealedYearError(
            f"HEAD {head[:12]} must be the freeze commit (origin {on_origin[:12]}, "
            f"local {local[:12]}): check out the tag"
        )
    if git("status", "--porcelain", "--untracked-files=no"):
        raise SealedYearError("tracked files differ from the freeze commit")
    _unlocked_at = head
    return head


def relock() -> None:
    """Lock the sealed years again (tests)."""
    global _unlocked_at
    _unlocked_at = None


def check_year(year: int, max_year: int) -> None:
    if _unlocked_at is None:
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
