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
DE_AT_PAIR = ["de_at", "at_de"]


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


def main() -> None:
    b = pd.read_csv(OUT / "bids_w12.csv")
    s = b.dropna(subset=["clearing", "realised_value"]).copy()
    # P&L of one right, at 1 MW, over its delivery month
    s["pnl_mwh"] = s["realised_value"] - s["clearing"]
    s["pnl_eur"] = s["pnl_mwh"] * s["realised_hours"]
    s["won"] = s["value"] >= s["clearing"]      # bid = model fair value, margin 0
    s["fs"] = s["pnl_mwh"] > 0                  # perfect foresight buys only winners

    full = monthly(s)
    ex = monthly(s[~s["border"].isin(DE_AT_PAIR)])

    corr = []
    for bd, g in s.groupby("border"):
        corr.append(dict(
            c=bd.upper().replace("_", "-"), n=len(g), n_won=int(g["won"].sum()),
            all=round(g["pnl_eur"].sum(), 1),
            mdl=round(g.loc[g["won"], "pnl_eur"].sum(), 1),
            fs=round(g.loc[g["fs"], "pnl_eur"].sum(), 1),
            clearing=round(g["clearing"].mean(), 2)))

    data = dict(
        full=full, ex_deat=ex, corridors=corr,
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
