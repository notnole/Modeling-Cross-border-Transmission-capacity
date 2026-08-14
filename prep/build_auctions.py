"""JAO monthly auction results for the borders this model can price.

What we need from JAO, per (corridor, delivery month):
    bid_gate_closure        the instant our bid is due - everything the model
                            reads must predate it, or the backtest is a lie
    auction_price_eur_mwh   the clearing price, paid on every delivered hour
    atc_mw / allocated_mw   size context

Source: `projects/capacities/data/auctions_monthly.parquet`, already pulled
through `plumbing.jao_auctions.monthly_results` (26 delivery months,
2024-08 -> 2026-09). If it is absent we re-pull the same thing per corridor.
Provenance is written to Data/jao_monthly_provenance.txt.

CZ-DE / DE-CZ are deliberately absent: per plumbing/jao_auctions/catalog.md
those corridors run **no monthly auctions**, so the model can price them but
there is nothing to bid into.

Usage
    python prep/build_auctions.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prep"))
from zones import PRICEABLE_BORDERS  # noqa: E402

SIBLING = ROOT.parent / "capacities" / "data" / "auctions_monthly.parquet"
OUT = ROOT / "Data" / "jao_monthly.csv"

# our directed border -> JAO corridor. Same direction convention: corridor X-Y
# is the right to transmit X->Y, worth P(Y) - P(X).
BORDER_TO_CORRIDOR = {b: b.upper().replace("_", "-") for b in PRICEABLE_BORDERS}

KEEP = ["corridor", "delivery_month", "product", "auction_price_eur_mwh",
        "offered_mw", "allocated_mw", "requested_mw", "atc_mw",
        "bidder_party_count", "bid_gate_closure", "delivery_start",
        "delivery_stop", "cancelled", "maintenance_hours",
        "maintenance_min_atc_mw"]


def from_sibling() -> tuple[pd.DataFrame, str]:
    d = pd.read_parquet(SIBLING)
    return d, f"{SIBLING} (mtime {pd.Timestamp(SIBLING.stat().st_mtime, unit='s')})"


def from_api(corridors: list[str], months: list[str]) -> tuple[pd.DataFrame, str]:
    from plumbing.jao_auctions import JaoAuctionsClient

    c = JaoAuctionsClient()
    frames = []
    for corr in corridors:
        for m in months:
            try:
                frames.append(c.monthly_results(corr, m))
            except Exception as exc:
                print(f"  {corr} {m}: {type(exc).__name__} {exc}"[:120])
    return pd.concat(frames, ignore_index=True), "plumbing.jao_auctions.monthly_results"


def main() -> None:
    corridors = sorted(set(BORDER_TO_CORRIDOR.values()))
    if SIBLING.exists():
        d, prov = from_sibling()
    else:
        months = [str(p) for p in pd.period_range("2024-08", "2026-09", freq="M")]
        d, prov = from_api(corridors, months)

    d = d[d["corridor"].isin(corridors) & (d["product"] == "BASE------")].copy()
    d = d[~d["cancelled"].fillna(False)]
    d = d[KEEP].sort_values(["corridor", "delivery_month"]).reset_index(drop=True)
    d.to_csv(OUT, index=False)
    (ROOT / "Data" / "jao_monthly_provenance.txt").write_text(prov + "\n")

    print(f"{len(d)} auctions, {d['corridor'].nunique()} corridors, "
          f"{d['delivery_month'].min()} -> {d['delivery_month'].max()}")
    print(f"provenance: {prov}")
    missing = sorted(set(corridors) - set(d["corridor"]))
    if missing:
        print(f"no monthly auctions for: {missing}")
    print()
    piv = d.pivot_table(index="delivery_month", columns="corridor",
                        values="auction_price_eur_mwh")
    print(piv.round(2).tail(14).to_string())


if __name__ == "__main__":
    main()
