# ruff: noqa: E501, B023
"""Markdown tables for docs/RESULTS.md, built only from reports/g3/ (results.json and the lines).

Run after `python -m sat.experiments.g3 score` and `reproduce`:
    uv run python scripts/g3/tables.py > reports/g3/tables.md
"""

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2] / "reports" / "g3"
NAMES = {"D1": "Wikipedia (D1)", "D3": "npm (D3)", "D4": "Library (D4)"}


def pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:+.{digits}f}%"


def share(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.3f}%"


def short(policy: str | None) -> str:
    if policy is None:
        return "none"
    return policy.replace("intelligent-tiering", "IT").replace(
        ":archive@90d:deep@180d", " (archive 90 d, deep 180 d)"
    )


def main() -> None:
    res = json.loads((ROOT / "results.json").read_text())
    base = pl.read_csv(ROOT / "base" / "lines.csv")
    out: list[str] = []
    out.append("## Hypotheses\n")
    out.append("| Hypothesis | Result |\n| --- | --- |")
    for h in ("H1", "H2", "H5", "H6", "H7", "H9"):
        out.append(
            f"| {h} | {'pass' if res.get(h) else 'fail' if res.get(h) is not None else 'not run'} |"
        )
    out.append("")
    b = res["scenarios"]["base"]
    out.append(
        "H1 by dataset: "
        + ", ".join(f"{NAMES[d]} {'yes' if v else 'no'}" for d, v in b["H1"].items())
    )
    out.append(
        "\nH2 by dataset: "
        + ", ".join(f"{NAMES[d]} {'yes' if v else 'no'}" for d, v in b["H2"].items())
    )
    out.append("\n## Base lines, matched waiting rule\n")
    out.append(
        "| Dataset | Pick, then score | Level | Rival pick | Rival cost (USD) | Rival waits | Ours | Ours cost (USD) | Gap | 95% interval | Ours waits | Waits no more | Wait hours (rival / ours) | Longest wait (rival / ours) |"
    )
    out.append(
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    for r in (
        base.filter(pl.col("rule") == "matched")
        .sort("dataset", "level", "pick_year")
        .iter_rows(named=True)
    ):
        ci = (
            "n/a"
            if r.get("ours_gap_ci_low") is None
            else f"{pct(r['ours_gap_ci_low'])} to {pct(r['ours_gap_ci_high'])}"
        )
        out.append(
            f"| {NAMES[r['dataset']]} | {r['pick_year']}, then {r['score_year']} | {r['level']} | {short(r['rival'])} | "
            f"{r['rival_cost']:.3f} | {share(r['rival_cold_rate'])} | {short(r['ours_policy'])} | {r['ours_cost']:.3f} | "
            f"{pct(r['ours_gap'])} | {ci} | {share(r['ours_cold_rate'])} | {'yes' if r['ours_wait_ok'] else 'no'} | "
            f"{r['rival_wait_hours']:,.0f} / {r['ours_wait_hours']:,.0f} | {r['rival_max_wait']:.0f} / {r['ours_max_wait']:.0f} h |"
        )
    out.append("\n## Base lines, equal 1% allowance (reported only)\n")
    out.append(
        "| Dataset | Pick, then score | Ours | Gap | Waits (rival / ours) | Wait hours (rival / ours) | Longest wait (rival / ours) |"
    )
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for r in (
        base.filter((pl.col("rule") == "equal") & (pl.col("level") == "L1"))
        .sort("dataset", "pick_year")
        .iter_rows(named=True)
    ):
        out.append(
            f"| {NAMES[r['dataset']]} | {r['pick_year']}, then {r['score_year']} | {short(r['ours_policy'])} | {pct(r['ours_gap'])} | "
            f"{share(r['rival_cold_rate'])} / {share(r['ours_cold_rate'])} | {r['rival_wait_hours']:,.0f} / {r['ours_wait_hours']:,.0f} | "
            f"{r['rival_max_wait']:.0f} / {r['ours_max_wait']:.0f} h |"
        )
    out.append("\n## H5: the scenarios\n")
    out.append("| Scenario | H1 (D1 / D3 / D4) | H1 holds | H2 (D1 / D3 / D4) | H2 holds |")
    out.append("| --- | --- | --- | --- | --- |")
    for name, e in res["scenarios"].items():

        def row(h: str) -> tuple[str, str]:
            v = e[h]
            cells = " / ".join("yes" if v.get(d) else "no" for d in ("D1", "D3", "D4"))
            return cells, "yes" if sum(v.get(d, False) for d in ("D1", "D3", "D4")) >= 2 else "no"

        h1c, h1h = row("H1")
        h2c, h2h = row("H2")
        out.append(f"| {name} | {h1c} | {h1h} | {h2c} | {h2h} |")
    out.append("\n## H3, H4, H6 (base)\n")
    out.append("| Line | H3 ours gap / ceiling gap |\n| --- | --- |")
    for k, v in b.get("H3_capture", {}).items():
        out.append(f"| {k} | {v:.2f} |")
    out.append("\n| Line | H4 ours against the seasonal-naive family alone |\n| --- | --- |")
    for k, v in b.get("H4_naive_gap", {}).items():
        out.append(f"| {k} | {pct(v)} |")
    out.append(
        "\n| Line | Core-hours | Saved (USD) | Compute / saving at 0.04 USD per core-hour | at 0.40 |\n| --- | --- | --- | --- | --- |"
    )
    for k, v in b.get("H6", {}).items():
        r = "n/a" if v["ratio"] is None else f"{100 * v['ratio']:.3f}%"
        r10 = "n/a" if v["ratio_at_10x"] is None else f"{100 * v['ratio_at_10x']:.3f}%"
        out.append(f"| {k} | {v['core_hours']:.3f} | {v['saved_usd']:.2f} | {r} | {r10} |")
    out.append("\n## Azure ZRS (reported): the chooser against smart tier\n")
    out.append("| Dataset | Pick year | Ours | Gap |\n| --- | --- | --- | --- |")
    for x in b.get("azure_zrs", []):
        out.append(
            f"| {NAMES[x['dataset']]} | {x['pick_year']} | {x['ours_policy']} | {pct(x['ours_gap'], 2)} |"
        )
    print("\n".join(out))


if __name__ == "__main__":
    main()
