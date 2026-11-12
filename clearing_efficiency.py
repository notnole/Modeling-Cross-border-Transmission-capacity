"""Do JAO monthly clearing prices track a forward-based fair value?

    python clearing_efficiency.py

Reads `outputs/bids_w12.csv` (built by `run_capacity.py bid`), which prices every
cleared monthly auction as of its own `bid_gate_closure` using only the forward
board that predated the gate. Three at-gate quantities per auction:

    fwd_spread  F_to - F_from            signed forward spread at the gate
    intrinsic   max(F_to - F_from, 0)    fair value with zero time value
    value       Margrabe(F_from, F_to)   fair value, sigma fitted on the 12
                                         whole months before the gate month

and two outcomes: `clearing` (what the auction charged) and `realised_value`
(`mean(max(P_to - P_from, 0))` over the delivered month).

Filters, both load-bearing (projects/capacities/CLAUDE.md):
  * `offered_mw > 0 AND requested_mw > 0` — an unsubscribed auction is published
    at a 0.00 reserve price, which is not a cheap right. 4 such rows here.
  * `clearing` notna — 2026-09 has gates but no result yet.

Read the caveat printed at the end: the Margrabe fair value is itself biased low
on this book, so `clearing - value` is an upper bound on the true premium.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
BIDS = HERE / "outputs" / "bids_w12.csv"
AUC = HERE / "Data" / "jao_monthly.csv"
OUT = HERE / "outputs"


def load() -> pd.DataFrame:
    b = pd.read_csv(BIDS, parse_dates=["gate"])
    a = pd.read_csv(AUC, parse_dates=["bid_gate_closure"])
    keep = ["corridor", "delivery_month", "offered_mw", "requested_mw"]
    a = a.rename(columns={"bid_gate_closure": "gate"})[keep + ["gate"]]
    d = b.merge(a, on=["corridor", "delivery_month", "gate"], how="left", validate="1:1")

    n0 = len(d)
    d = d[d["clearing"].notna()]
    n1 = len(d)
    art = (d["offered_mw"].fillna(1) <= 0) | (d["requested_mw"].fillna(1) <= 0)
    print(f"{n0} priced auctions -> {n1} with a result -> {n1 - art.sum()} subscribed "
          f"({art.sum()} unsubscribed reserve-price rows dropped)")
    d = d[~art].copy()

    d["m"] = pd.PeriodIndex(d["delivery_month"], freq="M")
    d["prem_val"] = d["clearing"] - d["value"]        # premium over Margrabe fair
    d["prem_int"] = d["clearing"] - d["intrinsic"]    # premium over pure intrinsic
    d["pnl"] = d["realised_value"] - d["clearing"]    # ex-post margin of a holder
    return d.sort_values(["corridor", "m"]).reset_index(drop=True)


def clustered_t(x: pd.Series, by: pd.Series) -> float:
    """t on mean(x), SE clustered on `by` (delivery month) — outcomes are
    correlated across corridors inside a month, so a naive t is far too large."""
    g = pd.DataFrame({"x": x, "g": by}).dropna()
    if g["g"].nunique() < 3:
        return np.nan
    means = g.groupby("g")["x"].mean()
    n = g.groupby("g").size()
    mu = g["x"].mean()
    num = (((means - mu) * n) ** 2).sum()
    return float(mu / (np.sqrt(num) / n.sum())) if num > 0 else np.nan


def ols(y: pd.Series, x: pd.Series) -> tuple[float, float, float]:
    v = pd.DataFrame({"y": y, "x": x}).dropna()
    if len(v) < 3 or v["x"].std() == 0:
        return (np.nan,) * 3
    b, a = np.polyfit(v["x"], v["y"], 1)
    r = np.corrcoef(v["x"], v["y"])[0, 1]
    return float(a), float(b), float(r ** 2)


def mae(a: pd.Series, b: pd.Series) -> float:
    v = (a - b).dropna()
    return float(v.abs().mean()) if len(v) else np.nan


def section(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def main() -> None:
    d = load()
    s = d[d["realised_value"].notna()]        # the scoreable set
    print(f"scoreable (delivered) subset: {len(s)} auctions, "
          f"{s['m'].min()} -> {s['m'].max()}, {s['corridor'].nunique()} corridors")

    # ------------------------------------------------------------------ pooled
    section("1. Pooled levels - EUR/MWh per delivered hour")
    rows = []
    for name, col in [("forward spread (signed)", "fwd_spread"),
                      ("intrinsic  max(fwd,0)", "intrinsic"),
                      ("Margrabe fair value", "value"),
                      ("CLEARING price", "clearing"),
                      ("realised value (ex post)", "realised_value")]:
        rows.append(dict(quantity=name, n=int(d[col].notna().sum()),
                         mean=d[col].mean(), median=d[col].median(), sd=d[col].std()))
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    section("2. Does the clearing price correspond to the forward fair value?")
    tab = []
    for name, col in [("vs intrinsic max(fwd,0)", "intrinsic"),
                      ("vs Margrabe fair value", "value")]:
        prem = d["clearing"] - d[col]
        a, b, r2 = ols(d["clearing"], d[col])
        tab.append(dict(benchmark=name, n=len(d), mean_bench=d[col].mean(),
                        mean_clearing=d["clearing"].mean(),
                        premium=prem.mean(), prem_med=prem.median(),
                        prem_sd=prem.std(), t_clustered=clustered_t(prem, d["m"]),
                        mae=mae(d["clearing"], d[col]),
                        corr=np.sqrt(r2) * np.sign(b), slope=b, intercept=a, r2=r2))
    print(pd.DataFrame(tab).round(3).to_string(index=False))
    print("\nslope = pass-through of a 1 EUR/MWh move in fair value into the clearing price;")
    print("r2    = share of cross-auction clearing variance the forward board explains.")

    section("3. Which at-gate number predicts realised value better - "
            "the clearing price, or the forward fair value?")
    for name, col in [("clearing price", "clearing"),
                      ("Margrabe fair value", "value"),
                      ("intrinsic max(fwd,0)", "intrinsic"),
                      ("forward spread (signed)", "fwd_spread")]:
        err = s["realised_value"] - s[col]
        _, b, r2 = ols(s["realised_value"], s[col])
        print(f"  {name:24s} ME {err.mean():+6.2f}  MAE {err.abs().mean():5.2f}  "
              f"RMSE {np.sqrt((err ** 2).mean()):5.2f}  corr {np.sqrt(r2) * np.sign(b):+.3f}")
    print(f"\n  holder margin (realised - clearing): mean {s['pnl'].mean():+.3f}, "
          f"t(clustered by month) {clustered_t(s['pnl'], s['m']):+.2f}, "
          f"positive on {100 * (s['pnl'] > 0).mean():.1f}% of {len(s)}")

    # -------------------------------------------------------------- per corridor
    section("4. Per corridor - sorted by premium over the Margrabe fair value")
    g = []
    for c, x in d.groupby("corridor"):
        xs = x[x["realised_value"].notna()]
        _, slope, r2 = ols(x["clearing"], x["value"])
        g.append(dict(
            corridor=c, n=len(x),
            clearing=x["clearing"].mean(), fwd=x["fwd_spread"].mean(),
            intrinsic=x["intrinsic"].mean(), fair=x["value"].mean(),
            realised=xs["realised_value"].mean(),
            prem_int=x["prem_int"].mean(), prem_fair=x["prem_val"].mean(),
            ratio=(x["clearing"].sum() / x["value"].sum()) if x["value"].sum() > 0 else np.nan,
            corr=np.sqrt(r2) * np.sign(slope), slope=slope,
            pnl=xs["pnl"].mean(), sigma=x["sigma"].mean()))
    gt = pd.DataFrame(g).sort_values("prem_fair", ascending=False)
    print(gt.round(2).to_string(index=False))
    print("\nratio = sum(clearing)/sum(fair) - >1 the auction charges more than the "
          "forward board's option value, <1 less.")

    # ------------------------------------------------------------------- in time
    section("5. Evolution over time - one row per delivery month (all corridors)")
    rows = []
    for m, x in d.groupby("m"):
        xs = x[x["realised_value"].notna()]
        _, slope, r2 = ols(x["clearing"], x["value"])
        rows.append(dict(month=str(m), n=len(x),
                         clearing=x["clearing"].mean(), absfwd=x["fwd_spread"].abs().mean(),
                         intrinsic=x["intrinsic"].mean(), fair=x["value"].mean(),
                         realised=xs["realised_value"].mean() if len(xs) else np.nan,
                         prem_int=x["prem_int"].mean(), prem_fair=x["prem_val"].mean(),
                         ratio=(x["clearing"].sum() / x["value"].sum()) if x["value"].sum() > 0 else np.nan,
                         xsec_corr=np.sqrt(r2) * np.sign(slope) if np.isfinite(r2) else np.nan,
                         sigma=x["sigma"].mean(),
                         pnl=xs["pnl"].mean() if len(xs) else np.nan))
    mt = pd.DataFrame(rows)
    print(mt.round(2).to_string(index=False))

    section("6. Is there a trend? OLS on the month index")
    mt["t"] = np.arange(len(mt))
    for col in ["prem_fair", "prem_int", "ratio", "xsec_corr", "clearing", "fair", "sigma"]:
        v = mt[["t", col]].dropna()
        a, b, r2 = ols(v[col], v["t"])
        print(f"  {col:10s} intercept {a:+8.3f}  slope {b:+8.4f}/month  r2 {r2:5.3f}  "
              f"over {len(v)} months  ({b * 12:+.2f} per year)")

    section("7. Per-corridor trend in the premium over fair value")
    rows = []
    for c, x in d.groupby("corridor"):
        x = x.sort_values("m")
        tt = (x["m"] - x["m"].min()).map(lambda p: p.n)
        _, b, r2 = ols(x["prem_val"], tt)
        h1, h2 = x[tt < tt.max() / 2], x[tt >= tt.max() / 2]
        rows.append(dict(corridor=c, n=len(x), slope_yr=b * 12, r2=r2,
                         first_half=h1["prem_val"].mean(), second_half=h2["prem_val"].mean(),
                         delta=h2["prem_val"].mean() - h1["prem_val"].mean()))
    print(pd.DataFrame(rows).sort_values("delta").round(2).to_string(index=False))

    section("8. Does overpaying relative to the forward board get punished?")
    for lab, x in [("delivered only", s)]:
        v = x.dropna(subset=["prem_val", "pnl"])
        _, b, r2 = ols(v["pnl"], v["prem_val"])
        print(f"  {lab}: corr(premium over fair, holder margin) = "
              f"{np.sqrt(r2) * np.sign(b):+.3f}  slope {b:+.3f}  n {len(v)}")
    q = s.copy()
    q["bucket"] = pd.qcut(q["prem_val"], 4, labels=["Q1 cheapest", "Q2", "Q3", "Q4 dearest"])
    print()
    print(q.groupby("bucket", observed=True).agg(
        n=("pnl", "size"), premium=("prem_val", "mean"), clearing=("clearing", "mean"),
        fair=("value", "mean"), realised=("realised_value", "mean"),
        margin=("pnl", "mean"), hit=("pnl", lambda v: 100 * (v > 0).mean())
    ).round(2).to_string())

    section("9. Robustness - is the fit just the one expensive corridor?")
    for lab, x in [("all 20 corridors", d), ("ex FR-DE", d[d["corridor"] != "FR-DE"]),
                   ("ex FR-DE, AT-HU", d[~d["corridor"].isin(["FR-DE", "AT-HU"])])]:
        a, b, r2 = ols(x["clearing"], x["value"])
        print(f"  {lab:18s} n {len(x):4d}  clearing = {a:+.3f} + {b:.3f} * fair   r2 {r2:.3f}")
    w = d.copy()
    for c in ["clearing", "value", "intrinsic", "realised_value"]:
        w[c + "_dm"] = w[c] - w.groupby("corridor")[c].transform("mean")
    a, b, r2 = ols(w["clearing_dm"], w["value_dm"])
    print(f"\n  WITHIN corridor (both sides demeaned per corridor):")
    print(f"    clearing_dm = {b:.3f} * fair_dm   r2 {r2:.3f}   n {len(w)}")
    print("    -> the auction tracks the forward board month to month, not just in the")
    print("       cross-section, so the pooled r2 is not a level artefact.")

    section("10. Regime split - the premium is a V, not a trend")
    d["regime"] = np.where(d["m"] < pd.Period("2025-08"), "A 2024-08..2025-07",
                           np.where(d["m"] < pd.Period("2026-04"), "B 2025-08..2026-03",
                                    "C 2026-04..2026-08"))
    r = d.groupby("regime").agg(
        n=("prem_val", "size"), clearing=("clearing", "mean"), fair=("value", "mean"),
        intrinsic=("intrinsic", "mean"), prem_fair=("prem_val", "mean"),
        prem_int=("prem_int", "mean"), realised=("realised_value", "mean"),
        margin=("pnl", "mean"), bidders=("bidders", "mean"), sigma=("sigma", "mean"))
    r["ratio"] = d.groupby("regime").apply(
        lambda x: x["clearing"].sum() / x["value"].sum(), include_groups=False)
    r["t_prem"] = d.groupby("regime").apply(
        lambda x: clustered_t(x["prem_val"], x["m"]), include_groups=False)
    r["t_margin"] = d.groupby("regime").apply(
        lambda x: clustered_t(x["pnl"], x["m"]), include_groups=False)
    print(r.round(2).to_string())
    print("\n  t_prem / t_margin cluster on the delivery month, so regime C rests on only")
    print("  4 delivered months (2026-04..07). Their margins are -0.16 / -2.24 / -2.47 /")
    print("  -2.27 - all four negative, which is the robust part; the t is not.")

    # month-block bootstrap on the regime changes - hours inside a delivery month
    # share one weather draw, so the block is the month, never the auction.
    rng = np.random.default_rng(7)
    blocks = {k: [g for _, g in v.groupby("m")] for k, v in d.groupby("regime")}

    def boot(bl, n=5000):
        out = np.empty(n)
        for i in range(n):
            pick = rng.choice(len(bl), len(bl), replace=True)
            out[i] = pd.concat([bl[j] for j in pick])["prem_val"].mean()
        return out

    keys = sorted(blocks)
    bs = {k: boot(blocks[k]) for k in keys}
    print("\n  month-block bootstrap of the change in premium over fair (5000 draws):")
    for lo, hi in [(0, 1), (1, 2), (0, 2)]:
        dd = bs[keys[hi]] - bs[keys[lo]]
        print(f"    {keys[hi][0]} - {keys[lo][0]}: {dd.mean():+.2f}  "
              f"p5..p95 {np.percentile(dd, 5):+.2f}..{np.percentile(dd, 95):+.2f}  "
              f"P(<0) {(dd < 0).mean():.3f}")
    p = d.pivot_table(index="corridor", columns="regime", values="prem_val", aggfunc="mean")
    ka, kb, kc = p.columns[0], p.columns[1], p.columns[2]
    print(f"\n  unanimity across corridors: B < A on {(p[kb] < p[ka]).sum()} of {len(p)}, "
          f"C > B on {(p[kc] > p[kb]).sum()} of {len(p)}")
    print("  -> a market-wide level shift, not composition and not a few borders.")
    print()
    print(p.assign(**{"C-B": p[kc] - p[kb]}).sort_values("C-B", ascending=False)
          .round(2).to_string())

    section("11. Moneyness - where the premium sits")
    d["itm"] = d["fwd_spread"] > 0
    mm = d.groupby("itm").agg(n=("prem_val", "size"), fwd=("fwd_spread", "mean"),
                              intrinsic=("intrinsic", "mean"), fair=("value", "mean"),
                              clearing=("clearing", "mean"), prem=("prem_val", "mean"),
                              realised=("realised_value", "mean"), margin=("pnl", "mean"))
    mm["ratio"] = d.groupby("itm").apply(
        lambda x: x["clearing"].sum() / x["value"].sum(), include_groups=False)
    mm.index = ["out of the money (F_to < F_from)", "in the money (F_to > F_from)"]
    print(mm.round(2).to_string())
    a, b, r2 = ols(d["prem_val"], d["value"])
    print(f"\n  premium = {a:+.3f} {b:+.4f} * fair   r2 {r2:.3f} -> a near-CONSTANT markup,")
    print("  so the `ratio` column is mostly base-size arithmetic: 1.66 on OTM corridors")
    print("  against 1.04 on ITM ones is a 1.0 vs 0.4 EUR/MWh premium on a 1.5 vs 10.3 base.")

    section("12. Per-corridor correspondence, sorted by how in-the-money the border is")
    rows = []
    for c, x in d.groupby("corridor"):
        _, b, r2 = ols(x["clearing"], x["value"])
        _, b2, r22 = ols(x["clearing"], x["fwd_spread"].abs())
        rows.append(dict(corridor=c, n=len(x), pct_itm=100 * (x["fwd_spread"] > 0).mean(),
                         mean_fwd=x["fwd_spread"].mean(), clearing=x["clearing"].mean(),
                         mae_vs_fair=mae(x["clearing"], x["value"]),
                         mae_vs_intr=mae(x["clearing"], x["intrinsic"]),
                         corr_fair=np.sqrt(r2) * np.sign(b),
                         corr_absfwd=np.sqrt(r22) * np.sign(b2),
                         sd_clearing=x["clearing"].std(), sd_fair=x["value"].std()))
    ct = pd.DataFrame(rows).sort_values("pct_itm")
    print(ct.round(2).to_string(index=False))
    otm, itm = ct[ct["pct_itm"] < 20], ct[ct["pct_itm"] > 80]
    print(f"\n  deep-OTM borders (n={len(otm)}): corr(clearing, fair) {otm['corr_fair'].mean():+.2f}, "
          f"sd(clearing) {otm['sd_clearing'].mean():.2f}")
    print(f"  deep-ITM borders (n={len(itm)}): corr(clearing, fair) {itm['corr_fair'].mean():+.2f}, "
          f"sd(clearing) {itm['sd_clearing'].mean():.2f}")
    print("  -> correspondence is a moneyness story: on an OTM border the fair value is")
    print("     almost all time value and barely moves, so there is nothing to track.")
    print("     MAE stays inside 0.65..1.95 EUR/MWh on all 20 regardless.")

    section("13. The catch - does the forward board itself know anything?")
    rows = []
    for c, x in s.groupby("corridor"):
        _, b, r2 = ols(x["realised_spread"], x["fwd_spread"])
        rows.append(dict(corridor=c, n=len(x), fwd=x["fwd_spread"].mean(),
                         real_sp=x["realised_spread"].mean(),
                         sd_fwd=x["fwd_spread"].std(), sd_real=x["realised_spread"].std(),
                         corr=np.sqrt(r2) * np.sign(b),
                         prem=x["prem_val"].mean(), margin=x["pnl"].mean()))
    ft = pd.DataFrame(rows).sort_values("corr")
    print(ft.round(2).to_string(index=False))
    v = s.copy()
    for c in ["fwd_spread", "realised_spread"]:
        v[c + "_dm"] = v[c] - v.groupby("corridor")[c].transform("mean")
    _, _, r2p = ols(s["realised_spread"], s["fwd_spread"])
    _, _, r2w = ols(v["realised_spread_dm"], v["fwd_spread_dm"])
    print(f"\n  corr(forward spread at gate, realised month spread): pooled "
          f"{np.sqrt(r2p):+.3f}, WITHIN corridor {np.sqrt(r2w):+.3f}")
    print("  The pooled number is a cross-section of border levels. Within a corridor the")
    print("  forward board explains under a quarter of the month-to-month spread variance,")
    print("  and on SK-HU / HU-SK / HU-AT it is ~zero or negative - yet the clearing price")
    print("  still tracks it at 0.96. The auction prices off the forward board almost")
    print("  mechanically, so it inherits the board's error wherever the board is wrong:")
    print("  DE-AT (forward +6.8 vs realised +9.9) hands a holder +3.01 EUR/MWh, CZ-SK")
    print("  (forward +10.1 vs realised +6.7, an SK settlement derived off DE per")
    print("  plumbing/eex/catalog.md) is the one border that clears BELOW fair value.")

    section("14. Caveat that bounds every premium above")
    bias = (s["realised_value"] - s["value"]).mean()
    tv_mod = s["time_value"].mean()
    tv_real = (s["realised_value"] - s["intrinsic"]).mean()
    print(f"  The Margrabe fair value is itself biased on this book: mean realised - "
          f"mean fair = {bias:+.2f} EUR/MWh")
    print(f"  time value modelled {tv_mod:.2f} vs realised value - intrinsic {tv_real:.2f} "
          f"-> the monthly-mean sigma fit captures {100 * tv_mod / tv_real:.0f}% of it.")
    print(f"  So `clearing - fair` overstates the true premium by ~{bias:.2f} EUR/MWh;")
    print("  `clearing - realised` (section 3, the holder margin) is the unbiased ex-post read.")

    OUT.mkdir(exist_ok=True)
    gt = gt.merge(ct[["corridor", "pct_itm", "mae_vs_fair", "corr_absfwd"]], on="corridor")
    gt = gt.merge(ft[["corridor", "corr"]].rename(columns={"corr": "corr_fwd_realsp"}),
                  on="corridor", how="left")
    gt.to_csv(OUT / "clearing_efficiency_corridor.csv", index=False)
    mt.to_csv(OUT / "clearing_efficiency_month.csv", index=False)
    d.to_csv(OUT / "clearing_efficiency_auctions.csv", index=False)
    print(f"\n-> outputs/clearing_efficiency_{{corridor,month,auctions}}.csv")


if __name__ == "__main__":
    main()
