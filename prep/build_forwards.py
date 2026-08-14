"""Decode FORWARD_PRODUCTS.xlsx into a tidy monthly-forward close panel.

Input format (long, one row per trade date x product):

    DateTime                 Product                              CurrentValues
    2023-01-02T00:00:00.000Z MD.EP.EEX.FY.BASE.FIX.MID.M.2026.09  141.51

    MD.EP.<exchange>.<root>.BASE.FIX.MID.<M|Q|Y>.<year>[.<period>]

`root` is the EEX short code, not the area code - decoded through
prep/zones.EEX_ROOT_TO_ZONE, which mirrors plumbing/eex/catalog.md. Every
product in the file is BASE and MID; there is no peak leg.

Traps handled
    * An expired or never-traded contract carries **0**, not NaN. 65.6% of rows
      are 0 and are dropped.
    * Year contracts have no period field -> 9 dot-fields, not 10.
    * Poland (FP / PLPX) has Year contracts only, so it is not mapped and drops
      out here.

Outputs
    Data/fwd_monthly.csv   trade_date, zone, delivery_month, close   (long)
    Data/fwd_price.csv     the `fwd_price_loader` shape (date + one column per
                           zone) for ONE delivery month, chosen by --month;
                           defaults to the first month with a full board on the
                           last trade date.

Usage
    python prep/build_forwards.py --xlsx "C:/Users/<you>/Downloads/FORWARD_PRODUCTS.xlsx"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prep"))
from zones import EEX_ROOT_TO_ZONE  # noqa: E402

DATA = ROOT / "Data"
DEFAULT_XLSX = Path.home() / "Downloads" / "FORWARD_PRODUCTS.xlsx"


def load_long(xlsx: Path) -> pd.DataFrame:
    df = pd.read_excel(xlsx)
    df["DateTime"] = pd.to_datetime(df["DateTime"], utc=True)

    p = df["Product"].astype(str).str.split(".", expand=True)
    df["root"] = p[3]
    df["mat"] = p[7]
    df["year"] = p[8]
    df["period"] = p[9] if p.shape[1] > 9 else None

    df["zone"] = df["root"].map(EEX_ROOT_TO_ZONE)
    df["close"] = pd.to_numeric(df["CurrentValues"], errors="coerce")

    m = df[(df["mat"] == "M") & df["zone"].notna() & (df["close"] > 0)].copy()
    m["delivery_month"] = pd.to_datetime(
        m["year"] + "-" + m["period"].str.zfill(2) + "-01"
    ).dt.to_period("M")
    m["trade_date"] = df["DateTime"].dt.tz_convert("UTC").dt.normalize()

    out = (m[["trade_date", "zone", "delivery_month", "close"]]
           .drop_duplicates(subset=["trade_date", "zone", "delivery_month"], keep="last")
           .sort_values(["trade_date", "delivery_month", "zone"])
           .reset_index(drop=True))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    ap.add_argument("--month", default=None, help="delivery month YYYY-MM for fwd_price.csv")
    args = ap.parse_args()

    long = load_long(args.xlsx)
    DATA.mkdir(exist_ok=True)
    long.to_csv(DATA / "fwd_monthly.csv", index=False)

    last = long["trade_date"].max()
    board = long[long["trade_date"] == last]
    print(f"{len(long)} monthly closes, {long['zone'].nunique()} zones, "
          f"trade dates {long['trade_date'].min().date()} -> {last.date()}")
    print("\nboard on the last trade date (EUR/MWh, BASE):")
    piv = board.pivot(index="delivery_month", columns="zone", values="close")
    print(piv.round(2).to_string())

    month = args.month or str(piv.index[0])
    row = long[(long["delivery_month"] == pd.Period(month, "M"))]
    wide = row.pivot(index="trade_date", columns="zone", values="close")
    wide.index = wide.index.strftime("%m/%d/%y")
    wide.index.name = "date"
    wide.to_csv(DATA / "fwd_price.csv")
    print(f"\nData/fwd_price.csv <- delivery month {month}, "
          f"{len(wide)} trade dates, zones {list(wide.columns)}")


if __name__ == "__main__":
    main()
