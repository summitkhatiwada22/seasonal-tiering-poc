import sys, os, polars as pl
S = str(__import__("pathlib").Path(__file__).parent / "outputs")
base = pl.read_csv("reports/e1/central/tune_results.csv")
for ds in sys.argv[1:]:
    if not os.path.exists(f"{S}/bulk_bulk_{ds}.csv"): print(ds, "not done"); continue
    std = pl.read_csv(f"{S}/bulk_std_{ds}.csv"); bulk = pl.read_csv(f"{S}/bulk_bulk_{ds}.csv")
    b = base.filter((pl.col("dataset")==ds)&(pl.col("cloud")=="aws"))
    # harness check: std csv equals saved tune numbers
    j = std.join(b.select(["policy","cost"]).rename({"cost":"saved"}), on="policy")
    print(ds, "harness max abs diff vs saved tune:", (j["cost"]-j["saved"]).abs().max(), "n=", j.height)
    for cap in (0.0, 0.01):
        riv = b.filter(pl.col("rival")&(pl.col("cold_rate")<=cap+1e-12))["cost"].min()
        out=[]
        for fam in ("seasonal","reactive","oracle"):
            r=[]
            for df in (std,bulk):
                d=df.filter((pl.col("family")==fam)&(pl.col("cold_rate")<=cap+1e-12))
                r.append(None if d.height==0 else d["cost"].min())
            out.append((fam,r))
        print(f"  cap {cap}: rival {riv:.3f}")
        for fam,(s,bk) in out:
            f=lambda x: "  -  " if x is None else f"{x:8.3f}"
            gain = "" if (s is None or bk is None) else f"  bulk saves {100*(1-bk/s):.1f}%"
            print(f"    {fam:9s} standard {f(s)}  bulk {f(bk)}{gain}   vs rival: std {'-' if s is None else f'{100*(1-s/riv):+.1f}%'} bulk {'-' if bk is None else f'{100*(1-bk/riv):+.1f}%'}")
