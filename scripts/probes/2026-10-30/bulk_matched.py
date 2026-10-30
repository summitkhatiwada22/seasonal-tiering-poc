import os, polars as pl
S = str(__import__("pathlib").Path(__file__).parent / "outputs")
base = pl.read_csv("reports/e1/central/tune_results.csv")
TOL = 1e-12
print("AWS 2022 in-sample, E1 rule: ours may wait no more than the rival pick. gap = 1 - ours/rival")
for ds in ("D1","D3","D4","D7"):
    b = base.filter((pl.col("dataset")==ds)&(pl.col("cloud")=="aws"))
    bulk = pl.read_csv(f"{S}/bulk_bulk_{ds}.csv"); aff = bulk["policy"].to_list()
    for lvl, cap in (("L0",0.0),("L1",0.01)):
        riv = b.filter(pl.col("rival")&(pl.col("cold_rate")<=cap+TOL)).sort("cost").row(0,named=True)
        lim = min(cap, riv["cold_rate"]) + TOL
        def best(df, fam="seasonal"):
            d = df.filter((pl.col("family")==fam)&(pl.col("cold_rate")<=lim))
            return None if d.height==0 else d.sort("cost").row(0,named=True)
        s = best(b)
        unaff = b.filter(~pl.col("policy").is_in(aff))
        cands = [x for x in (best(unaff), best(bulk)) if x]
        k = min(cands, key=lambda r: r["cost"]) if cands else None
        o_s, o_k = best(b,"oracle"), min([x for x in (best(unaff,"oracle"), best(bulk,"oracle")) if x], key=lambda r: r["cost"], default=None)
        g = lambda r: "   n/a" if r is None else f"{100*(1-r['cost']/riv['cost']):+6.1f}% (wait {r['cold_rate']:.4f})"
        print(f"{ds} {lvl}: rival {riv['cost']:.3f} wait {riv['cold_rate']:.4f} | ours std {g(s)} | ours bulk {g(k)} | oracle std {g(o_s)} | oracle bulk {g(o_k)}")
