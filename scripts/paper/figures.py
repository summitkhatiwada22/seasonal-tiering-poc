"""Figures for the paper (docs/RESULTS.md numbers, drawn). Post-hoc and descriptive: nothing here
changes a result. Every value is read from the committed reports, except two descriptive inputs
read from local data: the demand series (data/processed) and the chooser's per-file choices for the
sealed picks (data/g3/base), recomputed with the frozen code and checked against reports/g3.

    uv run --with matplotlib python scripts/paper/figures.py

Writes paper/figures/<name>.pdf (vector, for the paper) and <name>.png (for the web).
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.lines import Line2D

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "paper" / "figures"

# Palette: the first three categorical slots (validated all-pairs, CVD-safe), ink and status.
OURS, RIVAL, CEIL = "#2a78d6", "#eb6834", "#1baf7a"
SLOT4 = "#eda100"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
GOOD, BAD = "#0ca30c", "#d03b3b"
SEALED_WASH = "#f0efec"
NAMES = {"D1": "Wikipedia", "D3": "npm", "D4": "Library"}

mpl.rcParams.update(
    {
        "font.family": ["Inter", "DejaVu Sans"],
        "font.size": 8,
        "axes.titlesize": 8.5,
        "axes.labelsize": 8,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "legend.fontsize": 7.5,
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK2,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "text.color": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "lines.linewidth": 1.4,
        "pdf.fonttype": 42,
        "savefig.dpi": 220,
        "figure.dpi": 110,
    }
)

WIDTH = 6.3  # inches: the paper's text width


def save(fig: plt.Figure, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight", pad_inches=0.02)
    fig.savefig(OUT / f"{name}.png", bbox_inches="tight", pad_inches=0.06, facecolor="white")
    plt.close(fig)
    print("wrote", name)


def l1_lines() -> pl.DataFrame:
    """Matched-rule L1 lines of R1 (rolling years) and G3 (sealed years), base setting."""
    cols = [
        "dataset",
        "pick_year",
        "score_year",
        "ours_policy",
        "ours_gap",
        "ours_cold_rate",
        "rival_cold_rate",
        "ours_wait_ok",
        "ceiling_gap",
        "ceiling_cold_rate",
        "ceiling_wait_ok",
        "ours_wait_hours",
        "rival_wait_hours",
    ]
    r1 = pl.read_csv(REPO / "reports" / "r1" / "lines.csv")
    g3 = pl.read_csv(REPO / "reports" / "g3" / "base" / "lines.csv")
    keep = (pl.col("rule") == "matched") & (pl.col("level") == "L1")
    a = (
        r1.filter(keep)
        .select(cols)
        .with_columns(
            pl.lit("R1").alias("test"),
            pl.lit(None, pl.Float64).alias("lo"),
            pl.lit(None, pl.Float64).alias("hi"),
        )
    )
    b = (
        g3.filter(keep)
        .select(
            *cols, pl.col("ours_gap_ci_low").alias("lo"), pl.col("ours_gap_ci_high").alias("hi")
        )
        .with_columns(pl.lit("G3").alias("test"))
    )
    return pl.concat([a, b.select(a.columns)])


def passes(row: dict) -> bool:
    ok = row["ours_gap"] >= 0.05 and bool(row["ours_wait_ok"])
    if row["lo"] is not None:
        ok = ok and row["lo"] > 0
    return ok


# ------------------------------------------------------------------------------ figure 3


def demand_profiles() -> dict[str, pl.DataFrame]:
    """Within-year demand profile of the average file, per year: each file's demand divided by its
    own mean for that year, then averaged over the files active that year. Weekly for Wikipedia and
    npm (52 weeks), monthly for the library."""
    out = {}
    proc = REPO / "data" / "processed"
    for d, key in (("D1", "article"), ("D3", "package")):
        parts = []
        for p in sorted((proc / d).glob("year=*")):
            x = pl.read_parquet(p / "views.parquet").with_columns(
                pl.col(key).cast(pl.Categorical), pl.col("views").cast(pl.Float64)
            )
            x = x.with_columns(
                pl.col("date").dt.year().alias("year"),
                ((pl.col("date").dt.ordinal_day() - 1) // 7).alias("pos"),
            ).filter(pl.col("pos") < 52)
            m = x.group_by(key).agg(pl.col("views").mean().alias("m")).filter(pl.col("m") > 0)
            x = x.join(m, on=key).with_columns((pl.col("views") / pl.col("m")).alias("idx"))
            parts.append(x.group_by("year", "pos").agg(pl.col("idx").mean()))
        out[d] = pl.concat(parts).with_columns((pl.col("pos") + 0.5) / 52 * 12).sort("year", "pos")
    m = pl.concat(
        [
            pl.read_parquet(p / "monthly.parquet")
            for p in sorted((proc / "D4_sample").glob("year=*"))
        ]
    )
    m = m.filter(pl.col("year").is_between(2016, 2025))
    tot = m.group_by("key_id", "year").agg((pl.col("checkouts").sum() / 12).alias("m"))
    m = m.join(tot, on=["key_id", "year"]).with_columns(
        (pl.col("checkouts") / pl.col("m")).alias("idx")
    )
    active = tot.group_by("year").agg(pl.len().alias("n"))
    prof = m.group_by("year", "month").agg(pl.col("idx").sum()).join(active, on="year")
    prof = prof.with_columns(
        (pl.col("idx") / pl.col("n")).alias("idx"), (pl.col("month") - 0.5).alias("pos")
    )
    out["D4"] = prof.select("year", "pos", "idx").sort("year", "pos")
    return out


def fig_demand() -> None:
    data = demand_profiles()
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, 2.25), sharey=True, gridspec_kw={"wspace": 0.08})
    titles = {
        "D1": "Wikipedia (weekly)",
        "D3": "npm (weekly)",
        "D4": "Seattle library (monthly)",
    }
    for ax, d in zip(axes, ("D1", "D3", "D4"), strict=True):
        s = data[d]
        ax.axhline(1.0, color=AXIS, lw=0.7, zorder=0)
        for year in range(2016, 2026):
            y = s.filter(pl.col("year") == year)
            if year in (2024, 2025):
                c, lw, z = OURS, 1.3, 3
            elif year == 2020 and d == "D4":
                c, lw, z = RIVAL, 1.3, 2
            else:
                c, lw, z = "#c9c8c2", 0.8, 1
            ax.plot(y["pos"].to_list(), y["idx"].to_list(), color=c, lw=lw, zorder=z)
        ax.set_title(titles[d], loc="left", color=INK, fontweight="semibold")
        ax.set_xlim(0, 12)
        ax.set_xticks([0.5, 3.5, 6.5, 9.5], ["Jan", "Apr", "Jul", "Oct"])
        ax.tick_params(length=2.5)
    axes[0].set_ylim(0, 1.75)
    axes[0].set_ylabel("demand relative to\nthe year's mean")
    axes[2].text(4.6, 0.33, "2020", color=RIVAL, fontsize=7, fontweight="semibold")
    handles = [
        Line2D([], [], color="#c9c8c2", lw=0.9, label="2016–2023, one line per year"),
        Line2D([], [], color=OURS, lw=1.3, label="2024 and 2025 (sealed test years)"),
        Line2D([], [], color=RIVAL, lw=1.3, label="2020 (library closures)"),
    ]
    fig.legend(
        handles=handles, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.1)
    )
    save(fig, "fig3_demand")


# ------------------------------------------------------------------------------ figure 4


def fig_results() -> None:
    t = l1_lines()
    order = []
    for d in ("D1", "D3", "D4"):
        for test in ("R1", "G3"):
            sub = t.filter((pl.col("dataset") == d) & (pl.col("test") == test)).sort("score_year")
            order.extend(sub.iter_rows(named=True))
    fig, (a1, a2) = plt.subplots(
        1,
        2,
        figsize=(WIDTH, 3.7),
        sharey=True,
        gridspec_kw={"width_ratios": [1.2, 1.0], "wspace": 0.06},
    )
    ys, y, prev = [], 0.0, None
    for row in order:
        if prev is not None and row["dataset"] != prev:
            y += 0.9
        ys.append(y)
        prev = row["dataset"]
        y += 1
    ys_arr = np.array(ys)
    # left: gap with interval
    a1.axvspan(-45, 5, color=SEALED_WASH, lw=0, zorder=0)
    a1.axvline(0, color=AXIS, lw=0.8)
    a1.axvline(5, color=MUTED, lw=0.8, ls=(0, (3, 2)))
    for yy, row in zip(ys_arr, order, strict=True):
        g = row["ours_gap"] * 100
        filled = row["test"] == "G3"
        lo = row["lo"] * 100 if row["lo"] is not None else g
        hi = row["hi"] * 100 if row["hi"] is not None else g
        if row["lo"] is not None:
            a1.plot([lo, hi], [yy, yy], color=OURS, lw=1.6, solid_capstyle="round", zorder=2)
        a1.plot(g, yy, "o", ms=5, mfc=OURS if filled else "white", mec=OURS, mew=1.3, zorder=3)
        a1.text(hi + 2.2, yy, f"{g:+.1f}%", fontsize=6.8, color=INK2, ha="left", va="center")
    a1.set_xlim(-45, 72)
    a1.set_xticks([-40, -20, 0, 5, 20, 40, 60], ["-40", "-20", "0", "5", "20", "40", "60"])
    a1.set_xlabel("gap vs the rival (%), with 95% interval")
    a1.set_title("Cost", loc="left", color=INK, fontweight="semibold")
    labs = [
        f"{NAMES[r['dataset']]}, {r['test']}: {r['pick_year']}→{r['score_year']}" for r in order
    ]
    a1.set_yticks(ys_arr, labs)
    a1.invert_yaxis()
    a1.tick_params(axis="y", length=0)
    # right: waits ours vs rival (dumbbell)
    for yy, row in zip(ys_arr, order, strict=True):
        o, r = row["ours_cold_rate"] * 100, row["rival_cold_rate"] * 100
        over = o > r + 1e-12
        a2.plot(
            [r, o],
            [yy, yy],
            color=BAD if over else AXIS,
            lw=2.2 if over else 1.2,
            zorder=1,
            solid_capstyle="butt",
        )
        a2.plot(r, yy, "s", ms=4.2, mfc=RIVAL, mec="white", mew=0.6, zorder=3)
        a2.plot(
            o,
            yy,
            "o",
            ms=4.6,
            mfc=OURS if row["test"] == "G3" else "white",
            mec=OURS,
            mew=1.2,
            zorder=3,
        )
        why = []
        if row["ours_gap"] < 0.05:
            why.append("cost")
        if over:
            why.append(f"waits {o:.3f}% > {r:.3f}%")
        ok = not why and (row["lo"] is None or row["lo"] > 0)
        a2.text(
            1.02,
            yy,
            "✓ passes" if ok else "✗ " + ", ".join(why),
            transform=a2.get_yaxis_transform(),
            fontsize=6.8,
            color=GOOD if ok else BAD,
            va="center",
            ha="left",
            clip_on=False,
        )
    a2.set_xlim(0, 0.82)
    a2.set_xticks([0, 0.2, 0.4, 0.6, 0.8], ["0", "0.2%", "0.4%", "0.6%", "0.8%"])
    a2.set_xlabel("share of reads that waited for a restore")
    a2.set_title("Waiting", loc="left", color=INK, fontweight="semibold")
    a2.tick_params(axis="y", length=0)
    a2.spines["left"].set_visible(False)
    handles = [
        Line2D([], [], marker="o", ls="", mfc=OURS, mec=OURS, ms=5, label="ours, sealed test (G3)"),
        Line2D(
            [],
            [],
            marker="o",
            ls="",
            mfc="white",
            mec=OURS,
            mew=1.3,
            ms=5,
            label="ours, rolling years (R1)",
        ),
        Line2D(
            [],
            [],
            marker="s",
            ls="",
            mfc=RIVAL,
            mec="white",
            ms=4.5,
            label="rival: S3 Intelligent-Tiering",
        ),
        Line2D([], [], color=BAD, lw=2.2, label="ours waited more"),
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=4,
        frameon=False,
        bbox_to_anchor=(0.55, -0.07),
        handletextpad=0.4,
        columnspacing=1.2,
    )
    save(fig, "fig4_results")


# ------------------------------------------------------------------------------ figure 5


def fig_pass_region() -> None:
    t = l1_lines()
    fig, ax = plt.subplots(figsize=(WIDTH * 0.62, 3.0))
    ax.add_patch(plt.Rectangle((0, 5), 1.0, 60, color="#e5f4e4", lw=0, zorder=0))
    ax.text(
        0.04,
        7.5,
        "passes: 5% or more cheaper,\nwaits no more than the rival",
        fontsize=6.8,
        color="#006300",
        va="bottom",
    )
    ax.axhline(0, color=AXIS, lw=0.8)
    ax.axvline(1, color=MUTED, lw=0.8, ls=(0, (3, 2)))
    shape = {"D1": "o", "D3": "D", "D4": "^"}
    for row in t.iter_rows(named=True):
        rr = row["rival_cold_rate"]
        xo, yo = row["ours_cold_rate"] / rr, row["ours_gap"] * 100
        xc, yc = row["ceiling_cold_rate"] / rr, row["ceiling_gap"] * 100
        ax.plot([xc, xo], [yc, yo], color=GRID, lw=0.9, zorder=1)
        ax.plot(xc, yc, shape[row["dataset"]], ms=5.2, mfc=CEIL, mec="white", mew=0.7, zorder=2)
        ax.plot(xo, yo, shape[row["dataset"]], ms=5.2, mfc=OURS, mec="white", mew=0.7, zorder=3)
        if xo > 1.0 and yo > 5:
            ax.annotate(
                f"{NAMES[row['dataset']]} {row['score_year']}",
                (xo, yo),
                xytext=(6, -3),
                textcoords="offset points",
                fontsize=6.6,
                color=INK2,
            )
    ax.set_xlim(0, 3.2)
    ax.set_ylim(-42, 64)
    ax.set_xlabel("reads that waited, relative to the rival (1 = same)")
    ax.set_ylabel("gap vs the rival (%)")
    handles = [
        Line2D(
            [],
            [],
            marker="o",
            ls="",
            mfc=OURS,
            mec="white",
            ms=6,
            label="ours (picks from last year)",
        ),
        Line2D(
            [],
            [],
            marker="o",
            ls="",
            mfc=CEIL,
            mec="white",
            ms=6,
            label="ceiling (knows true read rates)",
        ),
        Line2D([], [], marker="o", ls="", mfc=MUTED, mec="white", ms=5, label="Wikipedia"),
        Line2D([], [], marker="D", ls="", mfc=MUTED, mec="white", ms=4.5, label="npm"),
        Line2D([], [], marker="^", ls="", mfc=MUTED, mec="white", ms=5, label="Library"),
    ]
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
    save(fig, "fig5_pass_region")


# ------------------------------------------------------------------------------ figure 6


def allocation() -> list[dict]:
    """Share of files, bytes and reads per kind of policy, under the chooser's sealed-year picks
    (recomputed with the frozen code; costs checked against reports/g3/base/lines.csv)."""
    from sat.experiments import chooser as ch
    from sat.experiments import g3, r1

    r1.use(g3.study("base", False))
    lines = pl.read_csv(REPO / "reports" / "g3" / "base" / "lines.csv").filter(
        (pl.col("rule") == "matched")
        & (pl.col("level") == "L1")
        & pl.col("ours_policy").str.starts_with("chooser")
    )

    def kind(name: str) -> str:
        if name == "intelligent-tiering":
            return "Intelligent-Tiering"
        if name.startswith(("lifecycle:deep_archive", "lifecycle:glacier_flexible")):
            return "Archive rule (Glacier, Deep Archive)"
        if name.startswith("seasonal"):
            return "Archive + forecast restores"
        return "Other"

    rows = []
    for x in lines.iter_rows(named=True):
        _, menu, mu, m = x["ours_policy"].split(":")
        s = ch.Setting(menu, float(mu[2:]), float(m[1:]))
        choice, prior = r1.chooser_chain(x["dataset"], "chooser", s)[x["score_year"]]
        run = r1.load_run(x["dataset"], x["score_year"], "actual")
        o = ch.outcome(
            run.cost,
            run.cold,
            run.hours,
            run.maxw,
            run.reads,
            choice,
            prior,
            ch.switch_charge(r1.sheet(), run.sizes),
        )
        if abs(o.cost - x["ours_cost"]) > 1e-9 * max(1.0, x["ours_cost"]):
            raise ValueError("recomputed chooser cost differs from the report")
        kinds = np.array([kind(run.names[i]) for i in choice])
        for k in (
            "Intelligent-Tiering",
            "Archive + forecast restores",
            "Archive rule (Glacier, Deep Archive)",
            "Other",
        ):
            sel = kinds == k
            rows.append(
                {
                    "dataset": x["dataset"],
                    "year": x["score_year"],
                    "policy": x["ours_policy"],
                    "kind": k,
                    "files": float(sel.mean()),
                    "bytes": float(run.sizes[sel].sum() / run.sizes.sum()),
                    "reads": float(run.reads[sel].sum() / run.reads.sum()),
                    "n_files": int(sel.sum()),
                    "median_mb": float(np.median(run.sizes[sel]) / 1e6) if sel.any() else 0.0,
                }
            )
    (REPO / "reports" / "g3" / "base").mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(REPO / "reports" / "g3" / "base" / "allocation.csv")
    return rows


def fig_allocation() -> None:
    rows = allocation()
    kinds = [
        "Intelligent-Tiering",
        "Archive + forecast restores",
        "Archive rule (Glacier, Deep Archive)",
        "Other",
    ]
    colors = [OURS, CEIL, RIVAL, AXIS]
    bars = []
    for d in ("D1", "D3"):
        for what in ("files", "bytes", "reads"):
            sel = [r for r in rows if r["dataset"] == d and r["year"] == 2024]
            bars.append((f"{NAMES[d]}, {what}", {r["kind"]: r[what] for r in sel}))
    fig, ax = plt.subplots(figsize=(WIDTH, 2.35))
    ys = [0, 1, 2, 3.5, 4.5, 5.5]
    for y, (_label, share) in zip(ys, bars, strict=True):
        left = 0.0
        for k, c in zip(kinds, colors, strict=True):
            w = share.get(k, 0.0) * 100
            if w <= 0:
                continue
            ax.barh(y, w, left=left, height=0.72, color=c, edgecolor="white", linewidth=1.2)
            if w >= 6:
                ax.text(
                    left + 1.0,
                    y,
                    f"{w:.0f}%",
                    va="center",
                    ha="left",
                    fontsize=7,
                    color="white" if c not in (AXIS,) else INK,
                )
            left += w
    ax.set_yticks(ys, [b[0] for b in bars])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100], ["0", "25%", "50%", "75%", "100%"])
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors]
    ax.legend(
        handles,
        kinds,
        loc="lower center",
        bbox_to_anchor=(0.45, -0.38),
        ncol=4,
        frameon=False,
        handlelength=1.0,
        columnspacing=1.2,
    )
    save(fig, "fig6_allocation")


# ------------------------------------------------------------------------------ figure 7


def fig_scenarios() -> None:
    res = json.loads((REPO / "reports" / "g3" / "results.json").read_text())
    names = {
        "base": "base",
        "storage-x0.5": "storage price ×0.5",
        "storage-x1.5": "storage price ×1.5",
        "fees-x0.5": "fees ×0.5",
        "fees-x1.5": "fees ×1.5",
        "restore-low": "restore times, low",
        "reads-low": "read scale, low",
        "reads-high": "read scale, high",
        "size-low": "file sizes, low",
        "size-high": "file sizes, high",
    }
    scen = list(names)
    fig, ax = plt.subplots(figsize=(WIDTH, 3.2))
    ax.axvspan(-80, 5, color=SEALED_WASH, lw=0, zorder=0)
    ax.axvline(0, color=AXIS, lw=0.8)
    ax.axvline(5, color=MUTED, lw=0.8, ls=(0, (3, 2)))
    col = {"D1": OURS, "D3": CEIL, "D4": RIVAL}
    off = {
        ("D1", 2024): -0.22,
        ("D1", 2025): -0.08,
        ("D3", 2024): 0.08,
        ("D3", 2025): 0.22,
        ("D4", 2024): -0.05,
        ("D4", 2025): 0.05,
    }
    for i, s in enumerate(scen):
        t = pl.read_csv(REPO / "reports" / "g3" / s / "lines.csv").filter(
            (pl.col("rule") == "matched") & (pl.col("level") == "L1")
        )
        for row in t.iter_rows(named=True):
            g = row["ours_gap"] * 100
            ok = row["ours_gap"] >= 0.05 and row["ours_wait_ok"] and row["ours_gap_ci_low"] > 0
            key = (row["dataset"], row["score_year"])
            ax.plot(
                g,
                i + off[key],
                "o",
                ms=5,
                mfc=col[row["dataset"]] if ok else "white",
                mec=col[row["dataset"]],
                mew=1.3,
                zorder=3,
            )
        held = [h for h in ("H1", "H2") if sum(res["scenarios"][s][h].values()) >= 2]
        ax.text(
            66,
            i,
            ", ".join(held) + " holds" if held else "—",
            va="center",
            fontsize=7,
            color=GOOD if held else MUTED,
            fontweight="semibold" if held else "normal",
        )
    ax.set_yticks(range(len(scen)), [names[s] for s in scen])
    ax.invert_yaxis()
    ax.set_xlim(-60, 80)
    ax.set_xticks([-50, -25, 0, 5, 25, 50])
    ax.set_xticklabels(["-50%", "-25%", "0", "5%", "25%", "50%"])
    ax.set_xlabel("gap vs the rival at L1, sealed years (filled = line passes, hollow = fails)")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    handles = [
        Line2D([], [], marker="o", ls="", mfc=col[d], mec=col[d], ms=5, label=NAMES[d]) for d in col
    ]
    ax.legend(
        handles=handles, loc="lower center", bbox_to_anchor=(0.45, -0.3), ncol=3, frameon=False
    )
    save(fig, "fig7_scenarios")


if __name__ == "__main__":
    fig_results()
    fig_pass_region()
    fig_scenarios()
    fig_allocation()
    fig_demand()
