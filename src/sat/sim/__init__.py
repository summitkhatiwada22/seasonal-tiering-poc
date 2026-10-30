"""Phase 3: cost and waiting-time simulator. Rules: docs/SIM_RULES.md."""

from sat.sim.engine import simulate, simulate_chunked
from sat.sim.managed import ITConfig, simulate_autoclass, simulate_intelligent_tiering
from sat.sim.model import (
    COST_CATEGORIES,
    Inventory,
    Plan,
    Restore,
    SimConfig,
    SimResult,
    WaitStats,
    merge_results,
)

__all__ = [
    "COST_CATEGORIES",
    "ITConfig",
    "Inventory",
    "Plan",
    "Restore",
    "SimConfig",
    "SimResult",
    "WaitStats",
    "merge_results",
    "simulate",
    "simulate_autoclass",
    "simulate_chunked",
    "simulate_intelligent_tiering",
]
