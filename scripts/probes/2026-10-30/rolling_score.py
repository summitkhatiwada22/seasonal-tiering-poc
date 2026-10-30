"""Pick on 2021 (E1 rules), score on 2022. AWS only. Usage: uv run python rolling_score.py D1 D3 D4"""
import os, sys, polars as pl
S = str(__import__("pathlib").Path(__file__).parent / "outputs")
TOL = 1e-12
t22 = pl.read_csv("reports/e1/central/tune_results.csv").filter(pl.col("cloud") == "aws")
for ds in sys.argv[1:]:
    std21 = pl.read_csv(f"{S}/roll21_std_{ds}.csv")
    blk21 = pl.read_csv(f"{S}/roll21_bulk_{ds}.csv")
    blk22 = pl.read_csv(f"{S}/bulk_bulk_{ds}.csv")
    a22 = t22.filter(pl.col("dataset") == ds)
    affected = set(blk21["policy"].to_list())
    print(f"== {ds}: pick on 2021, score on 2022 (AWS)")
    for lvl, cap in (("L0", 0.0), ("L1", 0.01)):
        riv = std21.filter(pl.col("rival") & (pl.col("cold_rate") <= cap + 1e-12)).sort("cost").row(0, named=True)
        lim = min(cap, riv["cold_rate"]) + TOL
        def best(pool):
            d = pool.filter((pl.col("family") == "seasonal") & (pl.col("cold_rate") <= lim))
            return None if d.height == 0 else d.sort("cost").row(0, named=True)
        std_pick = best(std21)
        unaff = std21.filter(~pl.col("policy").is_in(list(affected)))
        pool_bulk = pl.concat([unaff.with_columns(pl.lit("std").alias("mode")), blk21.with_columns(pl.lit("bulk").alias("mode"))], how="diagonal")
        bulk_pick = best(pool_bulk)
        r22 = a22.filter(pl.col("policy") == riv["policy"]).row(0, named=True)
        line = f" {lvl}: rival pick {riv['policy'][:42]} 2021 {riv['cost']:.3f} -> 2022 {r22['cost']:.3f} (wait {r22['cold_rate']:.4f})"
        print(line)
        for tag, pick, use_bulk in (("ours std ", std_pick, False), ("ours bulk", bulk_pick, True)):
            if pick is None:
                print(f"   {tag}: no setting qualifies"); continue
            if use_bulk and pick["policy"] in affected and pick.get("mode") == "bulk":
                row = blk22.filter(pl.col("policy") == pick["policy"]).row(0, named=True)
            else:
                row = a22.filter(pl.col("policy") == pick["policy"]).row(0, named=True)
            gap = 1 - row["cost"] / r22["cost"]
            ok = gap >= 0.05 and row["cold_rate"] <= r22["cold_rate"] + TOL
            print(f"   {tag}: {pick['policy'][:48]:48s} 2021 {pick['cost']:.3f} -> 2022 {row['cost']:.3f} gap {100*gap:+6.1f}% wait {row['cold_rate']:.4f} {'PASS' if ok else 'no'}")
