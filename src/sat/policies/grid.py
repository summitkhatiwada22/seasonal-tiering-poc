"""The configurations tried for every policy on every cloud (fixed before tuning; D-033, D-034).

Every family gets a comparable spread: the rivals every class the provider offers (lifecycle 30 or
90 days after upload) and the common settings of its managed service (widened on 2026-10-30, before
any real-data run, so the rival side is not under-tuned; D-033);
ours a few class pairs, two lead times and three recency windows for the warm/cold rule, three class
sets and three horizons for the fee-aware planner, and (AWS) Intelligent-Tiering with forecast
restores. The reactive and oracle references get the same shapes as the seasonal policy. Settings
are picked on 2022 (docs/E1_PROTOCOL.md); nothing here is adjusted after seeing real-data results.
"""

from __future__ import annotations

from sat.policies.planner import ITPrewarm, Planner
from sat.policies.policies import (
    Autoclass,
    AzureLastAccess,
    IntelligentTiering,
    Lifecycle,
    Policy,
    SmartTier,
    TwoTier,
)

LEADS = (7, 30)
RECENCIES = (7, 30, 90)
HORIZONS = (30, 90, 180)
PREWARM_IT = [(90, None), (90, 180)]  # (archive days, deep archive days) of Intelligent-Tiering

PAIRS = {
    "aws": [
        ("standard", "standard_ia"),
        ("standard", "glacier_instant"),
        ("standard", "glacier_flexible"),
        ("standard", "deep_archive"),
        ("glacier_instant", "glacier_flexible"),
        ("glacier_instant", "deep_archive"),
    ],
    "gcs": [
        ("standard", "nearline"),
        ("standard", "coldline"),
        ("standard", "archive"),
        ("nearline", "archive"),
    ],
    "azure": [("hot", "cool"), ("hot", "cold"), ("hot", "archive"), ("cool", "archive")],
}
ARCHIVE_CLASSES = {"aws": ["glacier_flexible", "deep_archive"], "gcs": [], "azure": ["archive"]}
PLANNER_CLASSES = {
    "aws": [
        ("standard", "standard_ia", "glacier_instant"),
        ("standard", "glacier_instant", "deep_archive"),
        ("standard", "standard_ia", "glacier_instant", "glacier_flexible", "deep_archive"),
    ],
    "gcs": [("standard", "nearline", "coldline"), ("standard", "nearline", "coldline", "archive")],
    "azure": [("hot", "cool", "cold"), ("hot", "cool", "cold", "archive")],
}
CLASSES = {
    "aws": ["standard", "standard_ia", "glacier_instant", "glacier_flexible", "deep_archive"],
    "gcs": ["standard", "nearline", "coldline", "archive"],
    "azure": ["hot", "cool", "cold", "archive"],
}


LIFECYCLE_AFTER = (30, 90)  # days after upload; for objects older than this, same as all-<class>
IT_SETTINGS = [  # (archive days, deep archive days); None = tier not activated
    (None, None),
    (90, None),
    (180, None),
    (None, 180),
    (90, 180),
    (90, 365),
]


def rivals(cloud: str) -> list[Policy]:
    first, *others = CLASSES[cloud]
    out: list[Policy] = [Lifecycle(cloud, first)]
    out += [Lifecycle(cloud, target, after) for target in others for after in LIFECYCLE_AFTER]
    if cloud == "aws":
        out += [IntelligentTiering(cloud, a, d) for a, d in IT_SETTINGS]
    elif cloud == "gcs":
        out += [Autoclass(cloud, "nearline"), Autoclass(cloud, "archive")]
    else:
        out += [
            AzureLastAccess(cloud, 30),
            AzureLastAccess(cloud, 30, cold_days=90),
            AzureLastAccess(cloud, 30, cold_days=90, archive_days=180),
            AzureLastAccess(cloud, 90, cold_days=180),
            AzureLastAccess(cloud, 30, archive_days=180),
        ]
    return out


def _variants(cloud: str) -> list[tuple[str, str, str]]:
    out = [(w, c, "move") for w, c in PAIRS[cloud]]
    out += [(CLASSES[cloud][0], c, "copy") for c in ARCHIVE_CLASSES[cloud]]
    return out


def _has_archive(cloud: str, classes: tuple[str, ...]) -> bool:
    return any(c in ARCHIVE_CLASSES[cloud] for c in classes)


def planners(cloud: str, kind: str) -> list[Policy]:
    out: list[Policy] = []
    for classes in PLANNER_CLASSES[cloud]:
        # the lead only matters when an archive class needs warming ahead; the oracle needs one day
        leads = LEADS if _has_archive(cloud, classes) and kind != "oracle" else (1,)
        for horizon in HORIZONS:
            for lead in leads:
                out.append(Planner(cloud, kind, classes, horizon, lead))
    if cloud == "aws" and kind in {"seasonal", "oracle"}:
        for archive_days, deep_days in PREWARM_IT:
            for lead in LEADS if kind == "seasonal" else (1,):
                out.append(ITPrewarm(cloud, kind, archive_days, deep_days, lead))
    return out


def ours(cloud: str, kind: str) -> list[Policy]:
    out: list[Policy] = planners(cloud, kind)
    for warm, cold, mode in _variants(cloud):
        if kind == "seasonal":
            for lead in LEADS:
                for recency in RECENCIES:
                    out.append(TwoTier(cloud, "seasonal", warm, cold, mode, lead, recency))
        elif kind == "reactive":
            for recency in RECENCIES:
                out.append(TwoTier(cloud, "reactive", warm, cold, mode, 1, recency))
        elif kind == "oracle":
            out.append(TwoTier(cloud, "oracle", warm, cold, mode, 1, 0))
        else:
            raise ValueError(kind)
    return out


def policy_grid(cloud: str) -> list[Policy]:
    return rivals(cloud) + ours(cloud, "seasonal") + ours(cloud, "reactive") + ours(cloud, "oracle")


# ------------------------------------------------------------------------------ round two (R1)
# Fixed in docs/R1_PROTOCOL.md before any rolling-year run of these settings (D-045). The E1 grid
# above is unchanged, so every E1 number can still be rebuilt.

BULK_ON_DEMAND = [  # rival: a lifecycle rule whose on-demand restores use AWS bulk speed
    (target, after) for target in ARCHIVE_CLASSES["aws"] for after in LIFECYCLE_AFTER
]


def _bulk_variants(kind: str) -> list[Policy]:
    """Ours and the reactive reference with planned restores (copy mode) and moves up out of an
    archive class at AWS bulk speed. Leads of 7 and 30 days cover the 48-hour bulk restore time."""
    out: list[Policy] = []
    for classes in PLANNER_CLASSES["aws"]:
        if not _has_archive("aws", classes):
            continue
        leads = LEADS if kind == "seasonal" else (1,)
        for horizon in HORIZONS:
            for lead in leads:
                out.append(Planner("aws", kind, classes, horizon, lead, "bulk"))
    for cold in ARCHIVE_CLASSES["aws"]:
        if kind == "seasonal":
            for lead in LEADS:
                for recency in RECENCIES:
                    out.append(
                        TwoTier("aws", "seasonal", "standard", cold, "copy", lead, recency, "bulk")
                    )
        else:
            for recency in RECENCIES:
                out.append(TwoTier("aws", "reactive", "standard", cold, "copy", 1, recency, "bulk"))
    return out


def round2_grid(cloud: str) -> list[Policy]:
    """Rivals (plus bulk on-demand restores), ours and the reactive reference, each with bulk
    variants. The oracle references are not run in round two; the forecastable ceiling replaces
    them (docs/R1_PROTOCOL.md)."""
    if cloud != "aws":
        raise ValueError("round two R1 runs on AWS only")
    out = rivals(cloud)
    out += [Lifecycle(cloud, t, a, "bulk") for t, a in BULK_ON_DEMAND]
    for kind in ("seasonal", "reactive"):
        out += ours(cloud, kind) + _bulk_variants(kind)
    return out


def can_wait(pol: Policy) -> bool:
    """Whether a read can ever wait under this policy (it uses a class that needs a restore)."""
    archive = set(ARCHIVE_CLASSES.get(pol.cloud, []))
    if isinstance(pol, Lifecycle):
        return pol.target in archive
    if isinstance(pol, IntelligentTiering):
        return bool(pol.archive_days or pol.deep_archive_days)
    if isinstance(pol, ITPrewarm):
        return True
    if isinstance(pol, TwoTier):
        return pol.cold in archive or pol.warm in archive
    if isinstance(pol, Planner):
        return any(c in archive for c in pol.classes)
    return True


# ------------------------------------------------------------------------------ Azure ZRS (D-049)
ZRS_CLASSES = ("hot", "cool", "cold")
ZRS_PAIRS = [("hot", "cool"), ("hot", "cold"), ("cool", "cold")]


def zrs_grid() -> list[Policy]:
    """Azure zone-redundant sheet (no archive tier): rivals including smart tier, ours and the
    reactive reference, built the same way as the E1 Azure grid minus the archive tier."""
    cloud = "azure"
    out: list[Policy] = [Lifecycle(cloud, "hot")]
    out += [Lifecycle(cloud, t, a) for t in ("cool", "cold") for a in LIFECYCLE_AFTER]
    out += [
        AzureLastAccess(cloud, 30),
        AzureLastAccess(cloud, 30, cold_days=90),
        AzureLastAccess(cloud, 90, cold_days=180),
        SmartTier(cloud),
    ]
    for horizon in HORIZONS:
        out.append(Planner(cloud, "seasonal", ZRS_CLASSES, horizon, 1))
        out.append(Planner(cloud, "reactive", ZRS_CLASSES, horizon, 1))
    for warm, cold in ZRS_PAIRS:
        for recency in RECENCIES:
            for lead in LEADS:
                out.append(TwoTier(cloud, "seasonal", warm, cold, "move", lead, recency))
            out.append(TwoTier(cloud, "reactive", warm, cold, "move", 1, recency))
    return out
