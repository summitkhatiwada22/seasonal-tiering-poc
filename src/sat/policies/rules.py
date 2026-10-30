"""Checks that a plan could be carried out on AWS as the provider's documentation allows.

The simulator bills whatever plan it is given; these rules decide which plans are allowed
(docs/evidence/official-prices-2026-10-30.md, Phase 4 section, read 2026-10-30):

1. **Waterfall.** Lifecycle moves only go down the order Standard > Standard-IA > Glacier Instant >
   Glacier Flexible > Deep Archive. Out of Glacier Flexible or Deep Archive an object can only come
   back by a restore and a copy; the simulator bills every move up out of those classes that way, so
   a plan can never skip the restore. The check confirms the price sheet's class order is this
   waterfall, which makes every "down" move in a plan a supported transition.
2. **Small objects.** "Objects smaller than 128 KB will not transition by default to any storage
   class." Our plans keep them in Standard for the whole window (no transition, no restore).
3. **Minimum durations in one rule.** "You can't create a single Lifecycle rule that transitions
   objects from one storage class to another before the minimum storage duration period has
   passed." Our lifecycle rules have one transition each, so this cannot be broken; the check is
   kept for multi-step rules.

The older rule "at least 30 days in Standard before Standard-IA" is not on the current pages and
is not enforced (all our lifecycle rules wait 30 days anyway).
"""

from __future__ import annotations

import numpy as np

from sat.policies.scenario import Scenario
from sat.sim import Plan

AWS_WATERFALL = ("standard", "standard_ia", "glacier_instant", "glacier_flexible", "deep_archive")


class PlanRuleError(ValueError):
    """A plan breaks a provider rule."""


def check_aws_plan(scn: Scenario, plan: Plan) -> None:
    if tuple(scn.sheet.tier_order) != AWS_WATERFALL:
        raise PlanRuleError(f"AWS class order {scn.sheet.tier_order} is not the waterfall")
    tier = np.asarray(plan.tier)
    small = scn.small()
    if (tier[small] != 0).any():
        bad = int(np.flatnonzero((tier[small] != 0).any(axis=1))[0])
        raise PlanRuleError(f"an object under 128 KB leaves Standard (row {bad} of the small ones)")
    small_ids = set(np.flatnonzero(small).tolist())
    if any(order.obj in small_ids for order in plan.restores):
        raise PlanRuleError("a restore is planned for an object under 128 KB (never archived)")


def check_lifecycle_steps(scn: Scenario, steps: list[tuple[int, str]]) -> None:
    """A multi-step lifecycle rule must leave each class only after its minimum duration."""
    order = list(scn.sheet.tier_order)
    for (day_a, tier_a), (day_b, tier_b) in zip(steps[:-1], steps[1:], strict=True):
        if order.index(tier_b) <= order.index(tier_a):
            raise PlanRuleError(f"{tier_a} -> {tier_b} is not a move down the waterfall")
        if day_b - day_a < scn.min_days(tier_a):
            raise PlanRuleError(
                f"{tier_a} is left after {day_b - day_a} days, before its "
                f"{scn.min_days(tier_a)}-day minimum"
            )
