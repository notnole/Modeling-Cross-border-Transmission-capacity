"""Add zones to the existing spot panel without re-pulling the ones already in it.

`build_spot.py` rebuilds all zones from scratch (~35 min for 11). When only a few
zones are new, this pulls just those and merges into Data/spot_hourly.parquet,
then rewrites the loader CSV. Same source and same UTC-hourly normalisation as
build_spot, so the merged columns are indistinguishable from a full rebuild.

Usage
    python prep/add_zones.py fr nl it gr [--start 2021-01-01]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prep"))
import build_spot as bs  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("zones", nargs="+")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default=str(dt.date.today()))
    args = ap.parse_args()

    panel = pd.read_parquet(bs.PARQUET)
    print(f"existing panel {panel.shape}, zones {list(panel.columns)}")

    for z in args.zones:
        if z in panel.columns:
            print(f"[{z}] already present, skipping")
            continue
        print(f"[{z}]", flush=True)
        s = bs.pull_entsoe(z, args.start, args.end)
        if s.empty:
            print(f"  {z}: nothing returned, not added")
            continue
        panel = panel.join(s, how="outer")

    panel = panel.sort_index()
    panel.index.name = "date"
    panel.to_parquet(bs.PARQUET)

    out = panel.copy()
    out.index = out.index.tz_convert("UTC").tz_localize(None)
    out.index.name = "date"
    out = out.reset_index()
    out["date"] = out["date"].dt.strftime("%Y %m %d %H")
    out.to_csv(bs.CSV, index=False)

    print(f"\n{bs.PARQUET.relative_to(ROOT)}  {panel.shape}")
    print(f"span {panel.index[0]} -> {panel.index[-1]} (UTC)")
    print("non-null share per zone:")
    print(panel.notna().mean().round(4).to_string())


if __name__ == "__main__":
    main()
