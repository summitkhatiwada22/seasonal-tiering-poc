import sys, polars as pl
ds, cl = sys.argv[1], sys.argv[2]
base = pl.read_csv("reports/e1/central/tune_results.csv").filter((pl.col("dataset")==ds)&(pl.col("cloud")==cl))
new = pl.read_csv(f"{__file__.rsplit('/',1)[0]}/outputs/pooled_{ds}_{cl}.csv")
def best(df, cap, f=None):
    d = df.filter(pl.col("cold_rate") <= cap + 1e-12)
    if f is not None: d = d.filter(f)
    return None if d.height == 0 else d["cost"].min()
print(f"{ds} {cl} (2022, central)")
for cap in (0.0, 0.01):
    riv = best(base, cap, pl.col("rival"))
    sp = best(base, cap, pl.col("policy").str.starts_with("seasonal-planner:"))
    rp = best(base, cap, pl.col("policy").str.starts_with("reactive-planner:"))
    op = best(base, cap, pl.col("policy").str.starts_with("oracle-planner:"))
    allours = best(base, cap, pl.col("family")=="seasonal")
    line = f" cap {cap}: rival {riv:.3f} | ours(all families) {allours:.3f} | seasonal-naive planner {sp} | reactive planner {rp} | oracle planner {op}"
    print(line)
    for th in sorted(new["theta"].unique()):
        n = best(new.filter(pl.col("theta")==th), cap)
        print(f"    pooled forecast theta={th}: {n}  ({'-' if n is None else f'{100*(1-n/riv):+.1f}% vs rival'})")
