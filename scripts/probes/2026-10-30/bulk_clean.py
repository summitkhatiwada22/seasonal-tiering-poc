import os, polars as pl
S = str(__import__("pathlib").Path(__file__).parent / "outputs")
base = pl.read_csv("reports/e1/central/tune_results.csv")
print("AWS, 2022, in-sample. gap = 1 - ours/rival (positive = ours cheaper). Best of the whole grid on each side.")
for ds in ("D1","D3","D4","D7"):
    b = base.filter((pl.col("dataset")==ds)&(pl.col("cloud")=="aws"))
    bulk = pl.read_csv(f"{S}/bulk_bulk_{ds}.csv")
    affected = set(bulk["policy"].to_list())
    for cap in (0.0, 0.01):
        ok = lambda d: d.filter(pl.col("cold_rate") <= cap + 1e-12)
        riv = ok(b.filter(pl.col("rival")))["cost"].min()
        out = {}
        for fam in ("seasonal","oracle"):
            std = ok(b.filter(pl.col("family")==fam))
            unaff = ok(b.filter((pl.col("family")==fam) & ~pl.col("policy").is_in(list(affected))))
            bk = ok(bulk.filter(pl.col("family")==fam))
            s = std["cost"].min() if std.height else None
            cands = [x for x in ((unaff["cost"].min() if unaff.height else None), (bk["cost"].min() if bk.height else None)) if x is not None]
            k = min(cands) if cands else None
            out[fam] = (s, k)
        g = lambda v: "  n/a " if v is None else f"{100*(1-v/riv):+6.1f}%"
        print(f"{ds} cap {cap:4}: rival {riv:7.3f} | ours std {g(out['seasonal'][0])} bulk {g(out['seasonal'][1])} | oracle std {g(out['oracle'][0])} bulk {g(out['oracle'][1])}")
