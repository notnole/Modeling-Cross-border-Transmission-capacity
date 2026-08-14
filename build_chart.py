"""Build outputs/profitability.html from chart_template.html + chart_data.json.

Same pattern as projects/capacities/build_chart.py: the template holds a
`__DATA__` placeholder and this inlines the JSON, because an Artifact's CSP
blocks every external fetch.

Data comes from `run_capacity.py bid`, which writes outputs/bids_w12.csv; this
script aggregates it into the three monthly series (model bid / buy everything /
perfect foresight) plus the per-corridor totals.

Run:  python run_capacity.py bid --window 12 && python build_chart.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "outputs"
# The two border groups where the auction left money on the table. Excluding
# BOTH is the honest control: excluding only DE-AT understates the model,
# because the German-Czech corridors are a second, larger source.
RICH_BORDERS = ["de_at", "at_de", "de_cz", "cz_de"]
# the fundamental model's own bid book, for the head-to-head. Its `bid` is the
# LGBM predicted-value p50 times a calibration factor k.
CAP_BIDS = HERE.parent / "capacities" / "price_model" / "outputs" / "bids_20260803.csv"


def monthly(sub: pd.DataFrame) -> list[dict]:
    rows = []
    for m, g in sub.groupby("delivery_month"):
        won, fs = g[g["won"]], g[g["fs"]]
        rows.append(dict(
            m=m, n=len(g), hours=int(g["realised_hours"].iloc[0]),
            all_eur=round(g["pnl_eur"].sum(), 1), all_n=len(g),
            mdl_eur=round(won["pnl_eur"].sum(), 1), mdl_n=int(len(won)),
            fs_eur=round(fs["pnl_eur"].sum(), 1), fs_n=int(len(fs)),
            mdl_mwh=round(won["pnl_mwh"].mean(), 2) if len(won) else None,
        ))
    return rows


def compare(s: pd.DataFrame) -> dict | None:
    """Head-to-head against projects/capacities' fundamental LGBM bid book.

    Joined on (corridor, delivery month). Both strategies are scored against
    THIS project's realised values so the target is identical — the two
    projects agree to 0.016 EUR/MWh mean anyway, computing the same
    `spread.clip(lower=0).mean()` over the delivery window from independent
    price pulls. The two exceptions: capacities' CZ-SK 2025-07 is 1.57 lower
    (its price file has NaN hours there, which its dropna() removes), and DST
    months differ by the one repeated CET hour its window counts.
    """
    if not CAP_BIDS.exists():
        print(f"skip comparison: {CAP_BIDS} not found")
        return None
    cap = pd.read_csv(CAP_BIDS)
    # join on the real corridor column: reconstructing it from the zone pair
    # cannot produce the TSO-split German names (`DE(50Hz)-CZ`).
    m = s.copy()
    j = (cap[["corridor", "month", "clearing", "p50", "bid"]]
         .merge(m[["corridor", "delivery_month", "value", "clearing", "intrinsic",
                   "realised_value", "realised_hours", "pnl_eur"]],
                left_on=["corridor", "month"], right_on=["corridor", "delivery_month"],
                suffixes=("_cap", ""))
         .dropna(subset=["clearing", "realised_value", "bid"]))
    if j.empty:
        return None

    j["buy_mar"] = j["value"] >= j["clearing"]
    j["buy_cap"] = j["bid"] >= j["clearing"]
    j["buy_both"] = j["buy_mar"] & j["buy_cap"]
    j["fs"] = j["realised_value"] > j["clearing"]
    ex = ~j["corridor"].isin(["DE-AT", "AT-DE"])
    ex_both = ex & ~j["corridor"].str.contains(r"DE\(", regex=True)

    def tot(mask):
        e = j.loc[mask, "pnl_eur"]
        t = (e.mean() / (e.std(ddof=1) / np.sqrt(len(e)))) if len(e) > 1 else None
        return dict(n=int(len(e)), total=round(e.sum(), 1),
                    mean=round(e.mean(), 1) if len(e) else 0.0,
                    t=round(t, 2) if t is not None else None,
                    hit=round(100 * (e > 0).mean(), 1) if len(e) else 0.0,
                    ex_n=int(mask.__and__(ex).sum()),
                    ex_total=round(j.loc[mask & ex, "pnl_eur"].sum(), 1),
                    ex2_n=int(mask.__and__(ex_both).sum()),
                    ex2_total=round(j.loc[mask & ex_both, "pnl_eur"].sum(), 1))

    strategies = [
        dict(key="all",  name="Buy everything",  v="--s-all",   **tot(pd.Series(True, index=j.index))),
        dict(key="cap",  name="Fundamental bid", v="--s-cap",   **tot(j["buy_cap"])),
        dict(key="mar",  name="Margrabe bid",    v="--s-model", **tot(j["buy_mar"])),
        dict(key="both", name="Both agree",      v="--s-both",  **tot(j["buy_both"])),
    ]
    accuracy = []
    for name, c in (("Margrabe value", "value"), ("Fundamental p50", "p50"),
                    ("Fundamental bid (p50 x k)", "bid"), ("Forward spread, floored", "intrinsic")):
        e = j[c] - j["realised_value"]
        accuracy.append(dict(name=name, me=round(e.mean(), 2), mae=round(e.abs().mean(), 2),
                             corr=round(j[c].corr(j["realised_value"]), 3)))

    monthly = []
    for mo, g in j.groupby("delivery_month"):
        monthly.append(dict(m=mo,
                            all=round(g["pnl_eur"].sum(), 1),
                            cap=round(g.loc[g["buy_cap"], "pnl_eur"].sum(), 1),
                            mar=round(g.loc[g["buy_mar"], "pnl_eur"].sum(), 1),
                            both=round(g.loc[g["buy_both"], "pnl_eur"].sum(), 1)))

    matrix = []
    for mb in (True, False):
        for cb in (True, False):
            e = j.loc[(j["buy_mar"] == mb) & (j["buy_cap"] == cb), "pnl_eur"]
            matrix.append(dict(mar=mb, cap=cb, n=int(len(e)),
                               mean=round(e.mean(), 1) if len(e) else None,
                               total=round(e.sum(), 1) if len(e) else 0.0))

    return dict(strategies=strategies, accuracy=accuracy, monthly=monthly, matrix=matrix,
                meta=dict(n=len(j), months=int(j["delivery_month"].nunique()),
                          corridors=int(j["corridor"].nunique()),
                          first=min(monthly, key=lambda r: r["m"])["m"],
                          last=max(monthly, key=lambda r: r["m"])["m"],
                          ceiling=round(j.loc[j["fs"], "pnl_eur"].sum(), 1),
                          ex_ceiling=round(j.loc[j["fs"] & ex, "pnl_eur"].sum(), 1),
                          ex2_ceiling=round(j.loc[j["fs"] & ex_both, "pnl_eur"].sum(), 1),
                          corridor_list=sorted(j["corridor"].unique()),
                          source=CAP_BIDS.name))


def main() -> None:
    b = pd.read_csv(OUT / "bids_w12.csv")
    s = b.dropna(subset=["clearing", "realised_value"]).copy()
    # P&L of one right, at 1 MW, over its delivery month
    s["pnl_mwh"] = s["realised_value"] - s["clearing"]
    s["pnl_eur"] = s["pnl_mwh"] * s["realised_hours"]
    s["won"] = s["value"] >= s["clearing"]      # bid = model fair value, margin 0
    s["fs"] = s["pnl_mwh"] > 0                  # perfect foresight buys only winners

    full = monthly(s)
    ex = monthly(s[~s["border"].isin(RICH_BORDERS)])

    corr = []
    for bd, g in s.groupby("corridor"):
        corr.append(dict(
            c=bd, n=len(g), n_won=int(g["won"].sum()),
            all=round(g["pnl_eur"].sum(), 1),
            mdl=round(g.loc[g["won"], "pnl_eur"].sum(), 1),
            fs=round(g.loc[g["fs"], "pnl_eur"].sum(), 1),
            clearing=round(g["clearing"].mean(), 2)))

    data = dict(
        full=full, ex_deat=ex, corridors=corr, compare=compare(s),
        meta=dict(n=len(s), months=len(full), corridors=int(s["border"].nunique()),
                  first=full[0]["m"], last=full[-1]["m"],
                  all_total=round(s["pnl_eur"].sum(), 1),
                  mdl_total=round(s.loc[s["won"], "pnl_eur"].sum(), 1),
                  fs_total=round(s.loc[s["fs"], "pnl_eur"].sum(), 1),
                  mdl_n=int(s["won"].sum()), fs_n=int(s["fs"].sum())))

    OUT.mkdir(exist_ok=True)
    (OUT / "chart_data.json").write_text(json.dumps(data), encoding="utf-8")

    tpl = (HERE / "chart_template.html").read_text(encoding="utf-8")
    blob = json.dumps(data)
    if "__DATA__" not in tpl:
        raise SystemExit("chart_template.html has no __DATA__ placeholder")
    if "</script" in blob.lower():
        raise SystemExit("JSON contains '</script' and would break out of the script tag")

    out = OUT / "profitability.html"
    out.write_text(tpl.replace("__DATA__", blob), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print(f"months {data['meta']['first']} -> {data['meta']['last']}, "
          f"{data['meta']['n']} rights, {data['meta']['corridors']} corridors")
    print(f"model {data['meta']['mdl_total']:+,.0f}  "
          f"buy-all {data['meta']['all_total']:+,.0f}  "
          f"foresight {data['meta']['fs_total']:+,.0f} EUR")


if __name__ == "__main__":
    main()
