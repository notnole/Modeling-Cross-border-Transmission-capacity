"""Build the hourly DAM spot panel the Margrabe model fits on.

Sources
    sk          OKTE /dam/results, column `price` (the Slovak DAM print).
                OKTE's priceCz/priceHu/priceRo/atc* columns are legacy and
                empty in every year checked (2023, 2024, 2025, 2026) - do not
                use them.
    everything  ENTSO-E day_ahead_prices per zone.
    else

Timestamps
    The canonical cache (Data/spot_hourly.parquet) is tz-aware UTC.
    Data/spot_current.csv is what the unmodified `loader.spot_loader` reads, so
    it must be naive '%Y %m %d %H' - it is written as **UTC wall clock**. That
    keeps the index unique and monotonic (the shipped Data/spot.csv is naive
    CET and therefore loses 02:00 on spring-forward and doubles it on
    fall-back). Consequence: base monthly means are taken over UTC hours, so a
    month boundary sits 1-2 h off the CET-defined EEX contract - 2 hours in
    ~720, immaterial for a base average. Delivery.peak/offpeak masks WOULD be
    wrong on a UTC index; the forwards are BASE-only so they are not used.

Resolution
    SK/CZ/HU/AT/... DA switched hourly -> 15-min on 2025-10-01. Everything is
    resampled to hourly means so one series spans the switch.

Usage
    python prep/build_spot.py [--start 2021-01-01] [--end today]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prep"))
from zones import OKTE_ZONES, ZONE_TO_ENTSOE  # noqa: E402

DATA = ROOT / "Data"
PARQUET = DATA / "spot_hourly.parquet"
CSV = DATA / "spot_current.csv"

ZONES = ("sk", "cz", "hu", "at", "de", "ro", "pl")


def _month_starts(start: str, end: str) -> list[tuple[str, str]]:
    ms = pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end), freq="MS")
    out = []
    for m in ms:
        last = (m + pd.offsets.MonthEnd(0)).date()
        out.append((str(m.date()), str(last)))
    return out


def pull_okte_sk(start: str, end: str) -> pd.Series:
    from plumbing.okte import OkteClient

    okte = OkteClient()
    frames = []
    for a, b in _month_starts(start, end):
        df = okte.get(
            "isot", "/dam/results",
            params={"deliveryDayFrom": a, "deliveryDayTo": b},
            parse_dates=["deliveryStart"],
        )
        if df.empty:
            continue
        s = df.set_index("deliveryStart")["price"].astype(float)
        frames.append(s)
        print(f"  okte sk {a[:7]}: {len(s)} rows", flush=True)
    s = pd.concat(frames).sort_index()
    idx = pd.DatetimeIndex(s.index)
    s.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return s[~s.index.duplicated()].resample("1h").mean().rename("sk")


def pull_entsoe(zone: str, start: str, end: str) -> pd.Series:
    from plumbing.entsoe import EntsoeClient

    ec = EntsoeClient()
    frames = []
    for y in range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1):
        a = max(pd.Timestamp(start), pd.Timestamp(f"{y}-01-01"))
        b = min(pd.Timestamp(end), pd.Timestamp(f"{y + 1}-01-01"))
        if a >= b:
            continue
        try:
            df = ec.day_ahead_prices(ZONE_TO_ENTSOE[zone], str(a.date()), str(b.date()))
        except Exception as exc:  # a zone/year with no publication
            print(f"  entsoe {zone} {y}: {type(exc).__name__} {exc}"[:160], flush=True)
            continue
        s = df["price_eur_mwh"].astype(float)
        s.index = s.index.tz_convert("UTC")
        frames.append(s)
        print(f"  entsoe {zone} {y}: {len(s)} rows", flush=True)
    if not frames:
        return pd.Series(dtype=float, name=zone)
    s = pd.concat(frames).sort_index()
    # keep="last": consecutive yearly chunks overlap on the Jan-1 boundary and
    # the earlier chunk truncates that hour to a single QH, so its hourly mean
    # would be one quarter instead of four.
    return s[~s.index.duplicated(keep="last")].resample("1h").mean().rename(zone)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default=str(dt.date.today()))
    args = ap.parse_args()

    cols = {}
    for z in ZONES:
        print(f"[{z}]", flush=True)
        cols[z] = pull_okte_sk(args.start, args.end) if z in OKTE_ZONES \
            else pull_entsoe(z, args.start, args.end)

    panel = pd.concat(cols.values(), axis=1).sort_index()
    panel.index.name = "date"
    DATA.mkdir(exist_ok=True)
    panel.to_parquet(PARQUET)

    out = panel.copy()
    out.index = out.index.tz_convert("UTC").tz_localize(None)
    out.index.name = "date"
    out = out.reset_index()
    out["date"] = out["date"].dt.strftime("%Y %m %d %H")
    out.to_csv(CSV, index=False)

    print(f"\n{PARQUET.relative_to(ROOT)}  {panel.shape}")
    print(f"{CSV.relative_to(ROOT)}")
    print(f"span {panel.index[0]} -> {panel.index[-1]} (UTC)")
    print("non-null share per zone:")
    print(panel.notna().mean().round(4).to_string())


if __name__ == "__main__":
    main()
