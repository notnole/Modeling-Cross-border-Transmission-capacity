"""Build outputs/profitability.html from chart_template.html + chart_data.json.

Same pattern as projects/capacities/build_chart.py: the template holds a
`__DATA__` placeholder and this inlines the JSON, because an Artifact's CSP
blocks every external fetch.

The page's subject is the **agreement bid** — one order at the LOWER of two
independent fair values, the forward-vol Margrabe model and the capacities
fundamental LGBM model. Because JAO monthly auctions are marginal-priced, that is
identical to "buy only where both models clear the price": `min(a,b) >= c` iff
both `a >= c` and `b >= c`, and you pay `c` either way.

That choice of subject sets the scope. The rule only exists where both books
carry a value, so **the whole page runs on the joined set** — one window
throughout, rather than a full book in some sections and the join in others,
which is what made earlier versions look self-contradictory.

Run:  python run_capacity.py bid --window 12 && python build_chart.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "outputs"

# The border groups where the auction left money on the table regardless of any
# model. Excluding BOTH is the honest control: excluding only DE-AT understates
# the rule, because the German-Czech corridors are a second, larger source.
RICH = ["DE-AT", "AT-DE", "DE(50Hz)-CZ", "DE(TenneT)-CZ", "CZ-DE(50Hz)", "CZ-DE(TenneT)"]


def _cap_bids() -> Path | None:
    """Freshest fundamental bid book. Prefer a local same-vintage copy (pulled
    from the box run) over the sibling project's older committed one."""
    local = sorted((HERE / "Data").glob("bids_2*.csv"))
    if local:
        return local[-1]
    sib = HERE.parent / "capacities" / "price_model" / "outputs" / "bids_20260803.csv"
    return sib if sib.exists() else None


def _t(e: pd.Series) -> float | None:
    return round(float(e.mean() / (e.std(ddof=1) / np.sqrt(len(e)))), 2) if len(e) > 1 else None


def load_joined() -> tuple[pd.DataFrame, str]:
    """One row per auction that BOTH models priced, with every rule's flag.

    Joined on (corridor, delivery month) — never on a corridor name rebuilt from
    a zone pair, which cannot produce the TSO-split German names. Both models are
    scored against THIS project's realised values so the target is identical; the
    two agree to 0.016 EUR/MWh mean from independent price pulls anyway.
    """
    src = _cap_bids()
    if src is None:
        raise SystemExit("no fundamental bid book found")
    cap = pd.read_csv(src)
    mar = pd.read_csv(OUT / "bids_w12.csv")

    j = (cap[["corridor", "month", "p50", "bid"]]
         .merge(mar[["corridor", "delivery_month", "value", "clearing", "intrinsic",
                     "realised_value", "realised_hours", "sigma"]],
                left_on=["corridor", "month"], right_on=["corridor", "delivery_month"])
         .dropna(subset=["clearing", "realised_value", "bid"]))

    j["pnl_mwh"] = j["realised_value"] - j["clearing"]
    j["pnl_eur"] = j["pnl_mwh"] * j["realised_hours"]      # 1 MW for the month
    j["lo"] = j[["value", "bid"]].min(axis=1)
    j["avg"] = j[["value", "bid"]].mean(axis=1)
    j["hi"] = j[["value", "bid"]].max(axis=1)
    j["buy_mar"] = j["value"] >= j["clearing"]
    j["buy_cap"] = j["bid"] >= j["clearing"]
    j["buy_lo"] = j["lo"] >= j["clearing"]                 # the subject
    j["buy_avg"] = j["avg"] >= j["clearing"]
    j["buy_hi"] = j["hi"] >= j["clearing"]
    j["fs"] = j["pnl_mwh"] > 0                             # perfect foresight
    j["rich"] = j["corridor"].isin(RICH)
    return j.sort_values(["delivery_month", "corridor"]).reset_index(drop=True), src.name


def monthly(sub: pd.DataFrame) -> list[dict]:
    rows = []
    for m, g in sub.groupby("delivery_month"):
        rows.append(dict(
            m=str(m), n=len(g), hours=int(g["realised_hours"].iloc[0]),
            all_eur=round(g["pnl_eur"].sum(), 1), all_n=len(g),
            lo_eur=round(g.loc[g["buy_lo"], "pnl_eur"].sum(), 1), lo_n=int(g["buy_lo"].sum()),
            mar_eur=round(g.loc[g["buy_mar"], "pnl_eur"].sum(), 1),
            cap_eur=round(g.loc[g["buy_cap"], "pnl_eur"].sum(), 1),
            fs_eur=round(g.loc[g["fs"], "pnl_eur"].sum(), 1), fs_n=int(g["fs"].sum()),
            lo_mwh=round(g.loc[g["buy_lo"], "pnl_mwh"].mean(), 2) if g["buy_lo"].any() else None,
        ))
    return rows


def main() -> None:
    j, src = load_joined()
    full = monthly(j)
    ex = monthly(j[~j["rich"]])

    corr = []
    for c, g in j.groupby("corridor"):
        corr.append(dict(
            c=c, n=len(g), n_won=int(g["buy_lo"].sum()),
            all=round(g["pnl_eur"].sum(), 1),
            lo=round(g.loc[g["buy_lo"], "pnl_eur"].sum(), 1),
            fs=round(g.loc[g["fs"], "pnl_eur"].sum(), 1),
            clearing=round(g["clearing"].mean(), 2),
            rich=bool(g["rich"].iloc[0])))

    # the strictness ladder. Nested by construction: lower subset average subset max.
    rules = []
    for name, mask, note in (
            ("Buy everything", pd.Series(True, index=j.index), "accept any price"),
            ("MAX of the two", j["buy_hi"], "either model clears"),
            ("Fundamental alone", j["buy_cap"], "its bid clears"),
            ("AVERAGE of the two", j["buy_avg"], "the average clears"),
            ("Margrabe alone", j["buy_mar"], "its value clears"),
            ("LOWER of the two", j["buy_lo"], "both models clear"),
            ("Perfect foresight", j["fs"], "the ceiling")):
        e = j.loc[mask, "pnl_eur"]
        rules.append(dict(name=name, note=note, n=int(len(e)),
                          total=round(e.sum(), 1), mean=round(e.mean(), 1), t=_t(e),
                          hit=round(100 * (e > 0).mean(), 1),
                          ex_n=int((mask & ~j["rich"]).sum()),
                          ex_mean=round(j.loc[mask & ~j["rich"], "pnl_eur"].mean(), 1)
                          if (mask & ~j["rich"]).any() else None))

    marg = []
    for name, inner, outer in (("average, beyond lower", j["buy_lo"], j["buy_avg"]),
                               ("max, beyond average", j["buy_avg"], j["buy_hi"])):
        e = j.loc[outer & ~inner, "pnl_eur"]
        marg.append(dict(name=name, n=int(len(e)), total=round(e.sum(), 1),
                         mean=round(e.mean(), 1) if len(e) else None,
                         hit=round(100 * (e > 0).mean(), 1) if len(e) else None))

    matrix = []
    for mb in (True, False):
        for cb in (True, False):
            e = j.loc[(j["buy_mar"] == mb) & (j["buy_cap"] == cb), "pnl_eur"]
            matrix.append(dict(mar=mb, cap=cb, n=int(len(e)),
                               mean=round(e.mean(), 1) if len(e) else None,
                               total=round(e.sum(), 1) if len(e) else 0.0))

    accuracy = []
    for name, col in (("Margrabe value", "value"), ("Fundamental p50", "p50"),
                      ("Fundamental bid", "bid"), ("The lower of the two", "lo"),
                      ("Forward spread, floored", "intrinsic")):
        e = j[col] - j["realised_value"]
        accuracy.append(dict(name=name, me=round(e.mean(), 2), mae=round(e.abs().mean(), 2),
                             corr=round(j[col].corr(j["realised_value"]), 3)))

    lo = j[j["buy_lo"]]
    exlo = j[j["buy_lo"] & ~j["rich"]]
    meta = dict(
        source=src, n=len(j), months=len(full), corridors=int(j["corridor"].nunique()),
        first=full[0]["m"], last=full[-1]["m"],
        all_total=round(j["pnl_eur"].sum(), 1),
        lo_total=round(lo["pnl_eur"].sum(), 1), lo_n=int(len(lo)),
        fs_total=round(j.loc[j["fs"], "pnl_eur"].sum(), 1), fs_n=int(j["fs"].sum()),
        mar_total=round(j.loc[j["buy_mar"], "pnl_eur"].sum(), 1),
        mar_n=int(j["buy_mar"].sum()),
        cap_total=round(j.loc[j["buy_cap"], "pnl_eur"].sum(), 1),
        cap_n=int(j["buy_cap"].sum()),
        lo_mwh=round(lo["pnl_mwh"].mean(), 2), lo_mwh_t=_t(lo["pnl_mwh"]),
        lo_eur_t=_t(lo["pnl_eur"]),
        lo_hit=round(100 * (lo["pnl_eur"] > 0).mean(), 1),
        ex_total=round(exlo["pnl_eur"].sum(), 1), ex_n=int(len(exlo)),
        ex_mean=round(exlo["pnl_eur"].mean(), 1) if len(exlo) else None,
        ex_all_total=round(j.loc[~j["rich"], "pnl_eur"].sum(), 1),
        ex_all_n=int((~j["rich"]).sum()),
        ex_all_mean=round(j.loc[~j["rich"], "pnl_eur"].mean(), 1),
        edge_corr=round((j["lo"] - j["clearing"]).corr(j["pnl_mwh"]), 3),
        months_pos=int(sum(1 for r in full if r["lo_eur"] > 0)),
        months_pos_all=int(sum(1 for r in full if r["all_eur"] > 0)),
    )

    data = dict(full=full, ex_rich=ex, corridors=corr, rules=rules,
                marginal=marg, matrix=matrix, accuracy=accuracy, meta=meta)

    OUT.mkdir(exist_ok=True)
    (OUT / "chart_data.json").write_text(json.dumps(data), encoding="utf-8")

    tpl = (HERE / "chart_template.html").read_text(encoding="utf-8")
    blob = json.dumps(data)
    if "__DATA__" not in tpl:
        raise SystemExit("chart_template.html has no __DATA__ placeholder")
    if "</script" in blob.lower():
        raise SystemExit("JSON contains '</script' and would break out of the script tag")

    page = tpl.replace("__DATA__", blob)
    # ASCII guard. The published page is body-level content, so it cannot carry a
    # <meta charset> and a host serving it as latin-1 renders every multi-byte
    # character as mojibake. Entities in HTML, backslash-uXXXX in JS. This
    # regressed three times; fail the build instead.
    bad = sorted({hex(ord(c)) for c in page if ord(c) > 127})
    if bad:
        lines = [f"  line {i}: {l.strip()[:90]}"
                 for i, l in enumerate(page.split(chr(10)), 1)
                 if any(ord(c) > 127 for c in l)]
        raise SystemExit("non-ASCII in the built page: " + ", ".join(bad) + chr(10)
                         + chr(10).join(lines[:10]))

    out = OUT / "profitability.html"
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print(f"fundamental book: {src}")
    print(f"{meta['n']} auctions, {meta['corridors']} corridors, "
          f"{meta['first']} -> {meta['last']}")
    print(f"agreement bid {meta['lo_total']:+,.0f} over {meta['lo_n']}  |  "
          f"buy-everything {meta['all_total']:+,.0f} over {meta['n']}  |  "
          f"ceiling {meta['fs_total']:+,.0f}")
    print(f"ex rich: agreement {meta['ex_total']:+,.0f} over {meta['ex_n']}, "
          f"buy-everything {meta['ex_all_total']:+,.0f} over {meta['ex_all_n']}")


if __name__ == "__main__":
    main()
