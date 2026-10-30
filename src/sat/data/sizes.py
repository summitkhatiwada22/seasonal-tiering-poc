"""Object sizes for datasets that have none (D1, D3, D4), decision D-009 refined by D-032.

Sizes are drawn from size distributions we measured in Phase 2 (records in ``data_records/``):

* ``low``: Wikimedia media files on 2023-07-02 (D2): median about 25 KB, mean about 200 KB.
* ``central``: the IBM cloud object store trace 004 (D5): median about 58 KB, a quarter of objects
  at 16-17 MB, mean about 20 MB.
* ``high``: the larger half of the same IBM trace (quantiles 0.5 to 1), median about 17 MB.

D2 has seven measured quantiles (p01 to p99) and a mean: the quantile function is interpolated
linearly in log size between them, flat below p01, with its top end (p100) set so the mean equals
the measured mean. The IBM trace has every percentile, p99.5, p99.9, the minimum and the maximum
(``sat.data.trace_sizes``), interpolated the same way with no fitting.

Every object gets one uniform draw ``u`` from a fixed seed, shared by the three settings, so an
object that is relatively large in one setting is relatively large in all of them. Size is
independent of popularity (an assumption).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

RECORDS = Path(__file__).resolve().parents[3] / "data_records"
SIZE_SEED = 20261030
_P = (0.01, 0.10, 0.25, 0.50, 0.75, 0.90, 0.99)
_KEYS = ("p01", "p10", "p25", "p50", "p75", "p90", "p99")


@dataclass(frozen=True)
class QuantileFunction:
    """Piecewise log-linear quantile function through ``(p, value)`` knots, p from 0 to 1."""

    p: tuple[float, ...]
    v: tuple[float, ...]

    def __call__(self, u: FloatArray) -> FloatArray:
        return np.exp(np.interp(u, self.p, np.log(self.v)))

    def mean(self, lo: float = 0.0, hi: float = 1.0) -> float:
        """Exact integral of the quantile function over [lo, hi], divided by (hi - lo)."""
        total = 0.0
        knots = sorted({lo, hi, *[x for x in self.p if lo < x < hi]})
        for a, b in zip(knots[:-1], knots[1:], strict=True):
            va, vb = float(self(np.array([a]))[0]), float(self(np.array([b]))[0])
            total += (
                (b - a) * va if math.isclose(va, vb) else (b - a) * (vb - va) / math.log(vb / va)
            )
        return total / (hi - lo)


def fit(quantiles: dict[str, float], mean: float) -> QuantileFunction:
    """Quantile function through the measured quantiles whose mean equals ``mean``.

    Flat below p01; the value at p=1 is found by bisection. If even a flat top end gives a mean
    above ``mean``, the top stays flat (reported by ``mean()``)."""
    values = [float(quantiles[k]) for k in _KEYS]
    p = (0.0, *_P, 1.0)

    def make(top: float) -> QuantileFunction:
        return QuantileFunction(p, (values[0], *values, top))

    lo, hi = math.log(values[-1]), math.log(values[-1]) + 30.0
    if make(math.exp(lo)).mean() >= mean:
        return make(math.exp(lo))
    for _ in range(200):
        mid = (lo + hi) / 2
        if make(math.exp(mid)).mean() < mean:
            lo = mid
        else:
            hi = mid
    return make(math.exp((lo + hi) / 2))


def _summary(path: Path) -> tuple[dict[str, float], float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    sizes = data.get("object_size", data)
    return sizes["size_quantiles_by_object"], float(sizes["mean_bytes_per_object"])


def _fine(path: Path) -> QuantileFunction:
    data = json.loads(path.read_text(encoding="utf-8"))
    levels = sorted((float(k), float(v)) for k, v in data["quantiles"].items())
    p = (0.0, *[a for a, _ in levels], 1.0)
    v = (float(data["min_bytes"]), *[b for _, b in levels], float(data["max_bytes"]))
    return QuantileFunction(p, v)


def size_settings(records: Path = RECORDS) -> dict[str, tuple[QuantileFunction, float, float]]:
    """Setting -> (quantile function, lower u, upper u)."""
    d2 = fit(*_summary(records / "D2" / "size_calibration.json"))
    d5 = _fine(records / "D5" / "size_quantiles_IBMObjectStoreTrace004Part0.json")
    return {"low": (d2, 0.0, 1.0), "central": (d5, 0.0, 1.0), "high": (d5, 0.5, 1.0)}


def draw_u(n: int, dataset_code: int, seed: int = SIZE_SEED) -> FloatArray:
    return np.random.default_rng([seed, dataset_code]).random(n)


def sizes_for(u: FloatArray, setting: str, records: Path = RECORDS) -> IntArray:
    qf, lo, hi = size_settings(records)[setting]
    return np.maximum(1, np.rint(qf(lo + (hi - lo) * u))).astype(np.int64)
