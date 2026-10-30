import os, polars as pl
S = str(__import__("pathlib").Path(__file__).parent / "outputs")
base = pl.read_csv("reports/e1/central/tune_results.csv")
def best(df, cap, f=None):
    d = df.filter(pl.col("cold_rate") <= cap + 1e-12)
    if f is not None: d = d.filter(f)
    return None if d.height == 0 else float(d["cost"].min())
print("2022 tuning data, planner family only; cost USD; best over settings (and theta where relevant)")
for cl, tag in (("aws","aws"),("azure","azure")):
    for ds in ("D1","D3","D4"):
        b = base.filter((pl.col("dataset")==ds)&(pl.col("cloud")==cl))
        pooled = pl.read_csv(f"{S}/pooled_{ds}_{tag}.csv") ; ro = pl.read_csv(f"{S}/rateoracle_{ds}_{tag}.csv")
        for cap in (0.0, 0.01):
            riv = best(b, cap, pl.col("rival"))
            vals = {
              "naive-last-year": best(b, cap, pl.col("policy").str.starts_with("seasonal-planner:")),
              "pooled": best(pooled, cap),
              "rate-oracle": best(ro, cap),
              "draw-knowing oracle": best(b, cap, pl.col("policy").str.starts_with("oracle-planner:")),
            }
            f = lambda v: "   -  " if v is None else f"{v:7.3f} ({100*(1-v/riv):+5.1f}%)"
            print(f"{ds} {cl:5s} cap {cap:4}: rival {riv:7.3f} | " + " | ".join(f"{k} {f(v)}" for k,v in vals.items()))
