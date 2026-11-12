"""Is the +0.69 EUR/MWh premium over Margrabe fair value genuine, or model error?

    python premium_source.py

`clearing_efficiency.py` measures the premium. This asks where it comes from, by
testing the four candidate explanations that the data can separate:

  1. STALE VOL.  The book's sigma is fitted on the 12 whole months BEFORE the
     gate, and fitted sigma trends up over the record (0.034 in 2023 -> 0.091 in
     2025 per CLAUDE.md). A trailing window in an uptrend is biased low, which
     would show up as a persistent positive "premium" that is not a premium.
     Test: refit sigma non-causally (12 months ending WITH the delivery month,
     and once on the whole record), reprice, and see how much of the 0.69 the
     repricing absorbs. Non-causal on purpose - a diagnostic, never a bid.

  2. VARIANCE RISK PREMIUM.  Invert Margrabe on the clearing price to get the
     auction's implied sigma, and on the realised value to get the sigma the
     outcome needed. If implied > needed systematically, buyers are paying for
     tail protection, which is a genuine premium and the standard finding in
     option markets.

  3. SCARCITY / MICROSTRUCTURE.  A uniform-price auction is cleared by the
     marginal bidder, so with 45-65 bidders and offered << requested the price
     sits high in the valuation distribution. Test the premium against
     bid-to-cover (requested/offered) and bidder count, controlling for level.

  4. MARK, NOT PRICE.  For illiquid EEX zones the settlement is derived off DE
     (plumbing/eex/catalog.md), so F_to - F_from is not a market view and
     "premium" is measurement error. Test liquid-zone borders against marked ones.

Every sigma here is a TOTAL vol (the p_soft Margrabe carries no time-to-maturity
term), so it is not annualised and must not be compared to a quoted vol.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "p_soft"))
sys.path.insert(0, str(HERE / "prep"))

from clearing_efficiency import clustered_t, load, ols  # noqa: E402

# EEX September-2026 open interest, from CLAUDE.md's liquidity table. A
# settlement on a 12-lot contract is a mark, not a price.
OI = {"de": 278853, "fr": 86930, "hu": 14068, "nl": 11818, "at": 2845,
      "cz": 2191, "ro": 1101, "sk": 482}
LIQUID = {"de", "fr", "hu", "nl"}          # >10k lots


def margrabe(S1, S2, sigma):
    """Vectorised copy of p_soft.capacity_class.Capacity.margrabe (which is
    scalar-only because it uses math.log). Verified identical below."""
    S1, S2, sigma = np.asarray(S1, float), np.asarray(S2, float), np.asarray(sigma, float)
    d1 = (np.log(S2 / S1) + 0.5 * sigma ** 2) / sigma
    return S2 * norm.cdf(d1) - S1 * norm.cdf(d1 - sigma)


def implied_sigma(S1: float, S2: float, target: float) -> float:
    """Invert Margrabe for the total vol. Monotone in sigma, bounded below by the
    intrinsic max(S2-S1,0) and above by S2, so anything outside is unattainable."""
    if not np.isfinite([S1, S2, target]).all() or min(S1, S2) <= 0:
        return np.nan
    lo, hi = 1e-6, 5.0
    if target <= margrabe(S1, S2, lo) or target >= margrabe(S1, S2, hi):
        return np.nan
    return float(brentq(lambda v: margrabe(S1, S2, v) - target, lo, hi, xtol=1e-8))


def fit_sigma_panel(windows: dict[str, tuple[pd.Timestamp, pd.Timestamp]],
                    borders: list[str]) -> pd.DataFrame:
    """{label: (start, end)} x borders -> long frame of fitted sig_mid.

    Uses run_capacity's own fit path so the numbers are comparable to the book:
    one ImplicitCapacity per border (capa_fit reads self.border[0]).
    """
    import run_capacity as rc
    rc.install_cached_spot_loader()
    rows = []
    for label, (start, end) in windows.items():
        caps = rc.fit_sigmas(borders, start.to_pydatetime(), end.to_pydatetime())
        for b, (cap, n) in caps.items():
            rows.append(dict(label=label, border=b, months=n,
                             sigma=np.nan if cap is None else cap.delivery["base"]["sig_mid"]))
    return pd.DataFrame(rows)


def main() -> None:
    d = load()
    borders = sorted(d["border"].unique())

    # ---- verify the vectorised Margrabe reproduces the book exactly ---------
    chk = margrabe(d["F_from"], d["F_to"], d["sigma"]) - d["value"]
    print(f"vectorised Margrabe vs the book's `value`: max|diff| {chk.abs().max():.2e}")
    assert chk.abs().max() < 1e-9, "reimplementation disagrees with p_soft"

    # ---- 1. non-causal sigma refits ----------------------------------------
    print("\nrefitting sigma non-causally (diagnostic only) ...")
    months = sorted(d["m"].unique())
    win = {}
    for m in months:
        # 12 months ending WITH the delivery month: the vol actually in force
        # around delivery, instead of the 12 that preceded the gate.
        end = (m + 1).to_timestamp() - pd.Timedelta(hours=1)
        start = (m - 11).to_timestamp()
        if end > pd.Timestamp("2026-07-31 23:00"):
            continue
        win[f"ctr|{m}"] = (start, end)
    win["full"] = (pd.Timestamp("2023-01-01"), pd.Timestamp("2026-07-31 23:00"))
    sig = fit_sigma_panel(win, borders)

    ctr = sig[sig["label"].str.startswith("ctr|")].copy()
    ctr["m"] = pd.PeriodIndex([s.split("|")[1] for s in ctr["label"]], freq="M")
    d = d.merge(ctr[["border", "m", "sigma"]].rename(columns={"sigma": "sigma_ctr"}),
                on=["border", "m"], how="left")
    full = sig[sig["label"] == "full"].set_index("border")["sigma"]
    d["sigma_full"] = d["border"].map(full)

    d["value_ctr"] = margrabe(d["F_from"], d["F_to"], d["sigma_ctr"])
    d["value_full"] = margrabe(d["F_from"], d["F_to"], d["sigma_full"])
    d["prem_ctr"] = d["clearing"] - d["value_ctr"]
    d["prem_full"] = d["clearing"] - d["value_full"]

    print("\n" + "=" * 78)
    print("1. STALE VOL - does a non-causal sigma absorb the premium?")
    print("=" * 78)
    v = d.dropna(subset=["value_ctr", "realised_value"])
    print(f"  on the {len(v)} auctions where a contemporaneous refit exists "
          f"({v['m'].min()} -> {v['m'].max()})\n")
    print(f"  {'sigma used':34s} {'mean sigma':>10s} {'mean fair':>10s} "
          f"{'premium':>8s} {'t':>6s} {'MAE vs realised':>16s}")
    for lab, sc, vc in [("12m BEFORE the gate (the book)", "sigma", "value"),
                        ("12m ending WITH delivery", "sigma_ctr", "value_ctr"),
                        ("whole record 2023-01..2026-07", "sigma_full", "value_full")]:
        prem = v["clearing"] - v[vc]
        print(f"  {lab:34s} {v[sc].mean():10.4f} {v[vc].mean():10.2f} "
              f"{prem.mean():+8.2f} {clustered_t(prem, v['m']):+6.2f} "
              f"{(v['realised_value'] - v[vc]).abs().mean():16.2f}")
    print(f"\n  sigma_ctr - sigma_bwd: mean {(v['sigma_ctr'] - v['sigma']).mean():+.4f}, "
          f"positive on {100 * (v['sigma_ctr'] > v['sigma']).mean():.0f}% of rows")
    print(f"  repricing moves the fair value by "
          f"{(v['value_ctr'] - v['value']).mean():+.2f} EUR/MWh, i.e. it absorbs "
          f"{100 * (v['value_ctr'] - v['value']).mean() / (v['clearing'] - v['value']).mean():.0f}% "
          f"of the {(v['clearing'] - v['value']).mean():.2f} premium.")

    # ---- 2. variance risk premium ------------------------------------------
    print("\n" + "=" * 78)
    print("2. VARIANCE RISK PREMIUM - auction-implied vol vs the vol the outcome needed")
    print("=" * 78)
    d["sig_imp"] = [implied_sigma(a, b, c) for a, b, c
                    in zip(d["F_from"], d["F_to"], d["clearing"])]
    d["sig_need"] = [implied_sigma(a, b, c) for a, b, c
                     in zip(d["F_from"], d["F_to"], d["realised_value"])]
    below = (d["clearing"] < d["intrinsic"] - 1e-9).sum()
    print(f"  {d['sig_imp'].notna().sum()} of {len(d)} clearing prices invert "
          f"({below} clear BELOW intrinsic, so no vol reproduces them)")
    w = d.dropna(subset=["sig_imp", "sig_need"])
    print(f"\n  on the {len(w)} auctions where both invert:")
    print(f"    sigma fitted at the gate      {w['sigma'].mean():.4f}")
    print(f"    sigma implied by CLEARING     {w['sig_imp'].mean():.4f}")
    print(f"    sigma the OUTCOME needed      {w['sig_need'].mean():.4f}")
    gap = w["sig_imp"] - w["sig_need"]
    print(f"    implied - needed              {gap.mean():+.4f}  median {gap.median():+.4f}  "
          f"t {clustered_t(gap, w['m']):+.2f}  implied high on {100 * (gap > 0).mean():.0f}%")
    print("    distribution of implied - needed, because the mean is not the story:")
    print("      " + "  ".join(f"p{p}={np.percentile(gap, p):+.3f}" for p in (5, 25, 50, 75, 95)))
    print(f"      skew {gap.skew():+.2f}; p95(needed) {w['sig_need'].quantile(.95):.3f} vs "
          f"p95(implied) {w['sig_imp'].quantile(.95):.3f}")
    print("      -> the typical auction implies slightly MORE vol than the outcome needed")
    print("         (median +0.008, high on 55%), and a thin left tail of months that")
    print("         needed far more than anyone implied drags the mean negative. That is")
    print("         what a fairly-priced long-option book looks like from the buyer side.")
    print("\n  by regime:")
    w = w.copy()
    w["regime"] = np.where(w["m"] < pd.Period("2025-08"), "A 2024-08..2025-07",
                           np.where(w["m"] < pd.Period("2026-04"), "B 2025-08..2026-03",
                                    "C 2026-04..2026-07"))
    print(w.groupby("regime").agg(n=("sig_imp", "size"), fitted=("sigma", "mean"),
                                  implied=("sig_imp", "mean"), needed=("sig_need", "mean"),
                                  ).round(4).to_string())

    # ---- 3. scarcity / microstructure --------------------------------------
    print("\n" + "=" * 78)
    print("3. SCARCITY AND COMPETITION - do they explain the premium?")
    print("=" * 78)
    d["cover"] = d["requested_mw"] / d["offered_mw"]
    d["alloc_share"] = d["allocated_mw"] / d["offered_mw"]
    q = d.dropna(subset=["cover", "prem_val"])
    print(f"  bid-to-cover (requested/offered) over {len(q)} auctions: "
          f"median {q['cover'].median():.1f}x, p10 {q['cover'].quantile(.1):.1f}x, "
          f"p90 {q['cover'].quantile(.9):.1f}x")
    for name, col in [("bid-to-cover", "cover"), ("log bid-to-cover", None),
                      ("bidder count", "bidders")]:
        x = np.log(q["cover"]) if col is None else q[col]
        a, b, r2 = ols(q["prem_val"], x)
        print(f"    premium ~ {name:18s} slope {b:+8.4f}  r2 {r2:5.3f}")
    # control for the level: the premium is additive, but big borders draw both
    # more bidders and higher clearing prices.
    qq = q.dropna(subset=["bidders", "value", "cover"])
    X = np.c_[np.ones(len(qq)), qq["value"], np.log(qq["cover"]), qq["bidders"]]
    beta, *_ = np.linalg.lstsq(X, qq["prem_val"].values, rcond=None)
    resid = qq["prem_val"].values - X @ beta
    r2 = 1 - resid.var() / qq["prem_val"].var()
    print(f"\n    premium = {beta[0]:+.3f} {beta[1]:+.4f}*fair {beta[2]:+.4f}*log(cover) "
          f"{beta[3]:+.4f}*bidders   r2 {r2:.3f}")
    print("    (all three controls together; compare the r2 to the single-variable fits)")
    # the decisive control: corridor and month fixed effects. Small borders are
    # both structurally oversubscribed and structurally different, and a regime
    # moves every corridor at once, so the raw slope could be either.
    q = q.copy()
    q["lc"] = np.log(q["cover"])
    for c in ["prem_val", "lc"]:
        q[c + "_fe"] = (q[c] - q.groupby("corridor")[c].transform("mean")
                        - q.groupby("m")[c].transform("mean") + q[c].mean())
    for lab, y, x in [("pooled ", "prem_val", "lc"), ("both FE", "prem_val_fe", "lc_fe")]:
        a, b, r2 = ols(q[y], q[x])
        print(f"    premium ~ log(cover), {lab}: slope {b:+.3f}  r2 {r2:.3f}")
    print()
    print(q.groupby(pd.qcut(q["cover"], 4)).agg(
        n=("prem_val", "size"), cover=("cover", "mean"), bidders=("bidders", "mean"),
        offered=("offered_mw", "mean"), fair=("value", "mean"),
        clearing=("clearing", "mean"), premium=("prem_val", "mean"),
        margin=("pnl", "mean")).round(2).to_string())

    # ---- 4. mark, not price -------------------------------------------------
    print("\n" + "=" * 78)
    print("4. MARK, NOT PRICE - is the premium bigger where the forward is a mark?")
    print("=" * 78)
    d["zf"], d["zt"] = d["border"].str.split("_").str[0], d["border"].str.split("_").str[1]
    d["oi_min"] = np.minimum(d["zf"].map(OI), d["zt"].map(OI))
    d["both_liquid"] = d["zf"].isin(LIQUID) & d["zt"].isin(LIQUID)
    print(f"  {'group':28s} {'n':>4s} {'min OI':>8s} {'fair':>7s} {'clearing':>9s} "
          f"{'premium':>8s} {'t':>6s} {'margin':>7s} {'MAE fair vs real':>17s}")
    for lab, x in [("both zones liquid (>10k)", d[d["both_liquid"]]),
                   ("at least one marked", d[~d["both_liquid"]])]:
        xs = x.dropna(subset=["realised_value"])
        print(f"  {lab:28s} {len(x):4d} {x['oi_min'].mean():8.0f} {x['value'].mean():7.2f} "
              f"{x['clearing'].mean():9.2f} {x['prem_val'].mean():+8.2f} "
              f"{clustered_t(x['prem_val'], x['m']):+6.2f} {xs['pnl'].mean():+7.2f} "
              f"{(xs['realised_value'] - xs['value']).abs().mean():17.2f}")
    a, b, r2 = ols(d["prem_val"], np.log(d["oi_min"]))
    print(f"\n    premium ~ log(min open interest): slope {b:+.4f}  r2 {r2:.3f}")

    # ---- 5. what the fair value actually misses ----------------------------
    print("\n" + "=" * 78)
    print("5. A REJECTED MECHANISM - keep the test, the hypothesis failed")
    print("=" * 78)
    print("  Hypothesis: capa_fit solves Margrabe(mean S_from, mean S_to, sigma) =")
    print("  mean_h(max(s_h,0)) on 12 monthly points, so its inputs are REALISED monthly")
    print("  means that already carry the spread dispersion; applying that sigma to")
    print("  F_to - F_from, a conditional mean compressed toward zero, would then")
    print("  underprice the option and manufacture a fake premium.")
    print("  It does not hold. The pooled dispersion ratio is ~1.0, and across corridors")
    print("  the sigma gap moves the WRONG way against it. Recorded so it is not retried.\n")
    sd = []
    for c, x in d.dropna(subset=["realised_spread"]).groupby("corridor"):
        wi = x.dropna(subset=["sig_imp"])
        sd.append(dict(corridor=c, n=len(x), sd_fwd=x["fwd_spread"].std(),
                       sd_real=x["realised_spread"].std(),
                       disp=x["realised_spread"].std() / x["fwd_spread"].std(),
                       sig_fit=x["sigma"].mean(),
                       sig_imp=wi["sig_imp"].mean(),
                       sig_gap=wi["sig_imp"].mean() - wi["sigma"].mean(),
                       prem=x["prem_val"].mean()))
    sdt = pd.DataFrame(sd).sort_values("disp")
    print(sdt.round(3).to_string(index=False))
    a, b, r2 = ols(sdt["sig_gap"], sdt["disp"])
    print(f"\n  across the 20 corridors: sigma_implied - sigma_fitted ~ "
          f"sd(realised spread)/sd(forward spread)")
    print(f"    slope {b:+.4f}  r2 {r2:.3f}  (n {len(sdt)})")
    a, b, r2 = ols(sdt["prem"], sdt["disp"])
    print(f"    premium ~ the same dispersion ratio: slope {b:+.3f}  r2 {r2:.3f}")
    print(f"\n  pooled: sd(realised monthly spread) {d['realised_spread'].std():.2f} vs "
          f"sd(forward spread at gate) {d['fwd_spread'].std():.2f} "
          f"= {d['realised_spread'].std() / d['fwd_spread'].std():.2f}x")

    print("\n" + "=" * 78)
    print("6. WHAT THE FAIR VALUE MISSES - the intra-month option, decomposed")
    print("=" * 78)
    s = d.dropna(subset=["realised_value"]).copy()
    s["real_intr"] = s["realised_spread"].clip(lower=0)
    s["real_tv"] = s["realised_value"] - s["real_intr"]
    print(f"  realised value                       {s['realised_value'].mean():6.2f}")
    print(f"  of which intrinsic on the MONTH mean {s['real_intr'].mean():6.2f}")
    print(f"  of which intra-month option value    {s['real_tv'].mean():6.2f}   <- "
          f"the thing a monthly-mean sigma has to stand in for")
    print(f"  modelled time value at the gate      {s['time_value'].mean():6.2f}   "
          f"({100 * s['time_value'].mean() / s['real_tv'].mean():.0f}% of it)")
    print(f"\n  so the fair value's shortfall vs realised is "
          f"{(s['realised_value'] - s['value']).mean():+.2f}, against a measured premium of "
          f"{s['prem_val'].mean():+.2f}")
    print(f"  residual after removing the model's own bias: "
          f"{s['prem_val'].mean() - (s['realised_value'] - s['value']).mean():+.2f} EUR/MWh")
    print(f"  which is the holder margin with its sign flipped: "
          f"{-s['pnl'].mean():+.2f} (t {clustered_t(s['pnl'], s['m']):+.2f})")

    d.to_csv(HERE / "outputs" / "premium_source.csv", index=False)
    sig.to_csv(HERE / "outputs" / "premium_source_sigma.csv", index=False)
    print("\n-> outputs/premium_source.csv, outputs/premium_source_sigma.csv")


if __name__ == "__main__":
    main()
