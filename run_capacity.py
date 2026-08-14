"""Run the p_soft Margrabe capacity model on current data.

Two modes, same model code (`p_soft/` classes, logic untouched):

  predict    Fit sigma on the trailing window, price every delivery month on
             the latest forward board. This is the forward-looking answer.
  backtest   Walk every delivery month that has both a forward board before it
             and realised spot inside it. Score the model against the realised
             mean payoff, with max(F2-F1, 0) as the no-option-value baseline.

Inputs (build them first):
  Data/spot_current.csv   prep/build_spot.py      hourly DAM, UTC wall clock
  Data/fwd_monthly.csv    prep/build_forwards.py  monthly BASE closes per zone

Modelling choices, all inherited from the original code and NOT changed here:
  * sigma is fitted on MONTHLY MEANS of (S1, S2, payoff) - one point per month
    in the window - by Levenberg-Marquardt against the Margrabe function.
  * scaling=1, i.e. no horizon rescaling of sigma.
  * base only: every product in the forward workbook is BASE, there is no peak
    leg to price.
  * `sig_low`/`sig_upp` are NOT reported: capa_fit builds them from
    curve_fit's covariance used as if it were a standard deviation
    (capacity_class.py:127-129), so the band is not a 1-sigma band.

Usage
  python run_capacity.py predict  [--window 12] [--asof 2026-08-06]
  python run_capacity.py backtest [--window 12]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")          # the model imports pyplot at module level
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "p_soft"))
sys.path.insert(0, str(ROOT / "prep"))

import Loaders.loader as ld                      # noqa: E402
import border_class as bc                        # noqa: E402
import capacity_class as capa                    # noqa: E402
from zones import PRICEABLE_BORDERS              # noqa: E402

SPOT_CSV = ROOT / "Data" / "spot_current.csv"
FWD_CSV = ROOT / "Data" / "fwd_monthly.csv"
OUT = ROOT / "outputs"


# --------------------------------------------------------------------------
# read the spot CSV once and serve slices, so a 40-month walk does not re-read
# it 40 times. Same return shape as the original spot_loader.
# --------------------------------------------------------------------------
def install_cached_spot_loader() -> pd.DataFrame:
    df = pd.read_csv(SPOT_CSV)
    df["date"] = pd.to_datetime(df["date"], format="%Y %m %d %H")
    df = df.set_index("date").sort_index()

    def spot_loader(country_list=None, bT=None, eT=None, path=None):
        cl = list(df) if country_list is None else country_list
        a = df.first_valid_index() if bT is None else bT
        b = df.last_valid_index() if eT is None else eT
        return df.loc[a:b, cl]

    ld.spot_loader = spot_loader
    bc.ld.spot_loader = spot_loader
    return df


def window_bounds(first_delivery: pd.Timestamp, window: int):
    """Trailing `window` whole months ending the hour before `first_delivery`."""
    end = first_delivery.replace(day=1, hour=0, minute=0, second=0) - pd.Timedelta(hours=1)
    start = end.replace(day=1, hour=0) - pd.DateOffset(months=window - 1)
    return start, end


def load_forwards() -> pd.DataFrame:
    f = pd.read_csv(FWD_CSV, parse_dates=["trade_date"])
    f["delivery_month"] = pd.PeriodIndex(f["delivery_month"], freq="M")
    return f


def fit_sigmas(borders: list[str], start: dt.datetime, end: dt.datetime) -> dict:
    """One ImplicitCapacity per border.

    Deliberately one object per border: capa_fit/plot read self.border[0], so a
    multi-border ImplicitCapacity silently fits only the first border
    (capacity_class.py:119-123). Constructing them singly avoids that without
    touching the class.
    """
    bs = bc.DataBorderClass(borders, ["implicit"] * len(borders), start, end)
    bs.load_data()
    monthly = bs.aggregate_data("M", delivery="base")

    out = {}
    for b in borders:
        n = len(monthly[b])
        if n < 6:
            out[b] = (None, n)
            continue
        cap = capa.ImplicitCapacity([b], ["base"])
        try:
            cap.capa_fit(monthly, "base", scaling=1)
        except Exception as exc:
            print(f"  fit failed {b}: {type(exc).__name__} {exc}"[:120])
            out[b] = (None, n)
            continue
        out[b] = (cap, n)
    return out


def price_board(caps: dict, board: pd.DataFrame) -> pd.DataFrame:
    """board: one row per (zone, delivery_month) close on a single trade date."""
    px = board.set_index(["delivery_month", "zone"])["close"]
    rows = []
    for month in board["delivery_month"].unique():
        for b, (cap, n) in caps.items():
            z1, z2 = b.split("_")
            try:
                F1, F2 = float(px[(month, z1)]), float(px[(month, z2)])
            except KeyError:
                continue
            if cap is None or not np.isfinite([F1, F2]).all() or min(F1, F2) <= 0:
                continue
            sigma = cap.delivery["base"]["sig_mid"]
            value = cap.capa_price_mid(F1, F2, "base")
            d1, d2 = cap.capa_delta(F1, F2, "base")
            rows.append(dict(border=b, delivery_month=str(month), F_from=F1, F_to=F2,
                             fwd_spread=F2 - F1, intrinsic=max(F2 - F1, 0.0),
                             sigma=sigma, value=value,
                             time_value=value - max(F2 - F1, 0.0),
                             delta_from=d1, delta_to=d2, fit_months=n))
    return pd.DataFrame(rows)


def realised(spot: pd.DataFrame, border: str, month: pd.Period) -> dict:
    z1, z2 = border.split("_")
    if z1 not in spot or z2 not in spot:
        return {}
    w = spot.loc[str(month)]
    s = (w[z2] - w[z1]).dropna()
    if len(s) < 24 * 20:
        return {}
    return dict(realised_value=float(s.clip(lower=0).mean()),
                realised_spread=float(s.mean()),
                realised_hours=len(s),
                spot_from=float(w[z1].mean()), spot_to=float(w[z2].mean()))


def cmd_predict(args) -> None:
    spot = install_cached_spot_loader()
    fwd = load_forwards()

    if args.asof:
        asof = pd.Timestamp(args.asof).tz_localize("UTC")
    else:
        # last date with a real board: the workbook has non-trading-day rows
        # where every settlement is 0 and therefore dropped upstream
        per_date = fwd.groupby("trade_date")["zone"].nunique()
        asof = per_date[per_date >= 5].index.max()
    board = fwd[fwd["trade_date"] == asof]
    if board.empty:
        raise SystemExit(f"no forward board on {asof.date()}; "
                         f"last is {fwd['trade_date'].max().date()}")

    # fit on whole months only: the window ends the hour before the current
    # (incomplete) month starts
    start, end = window_bounds(spot.index.max(), args.window)
    print(f"forward board  {asof.date()}   (spot to {spot.index.max()})")
    print(f"sigma window   {start.date()} -> {end.date()}  ({args.window} months, base)\n")

    caps = fit_sigmas(PRICEABLE_BORDERS, start.to_pydatetime(), end.to_pydatetime())
    res = price_board(caps, board)
    if res.empty:
        raise SystemExit("nothing priced")

    OUT.mkdir(exist_ok=True)
    path = OUT / f"prediction_{asof.date()}_w{args.window}.csv"
    res.to_csv(path, index=False)

    show = res.copy()
    for c in ("F_from", "F_to", "fwd_spread", "intrinsic", "value", "time_value"):
        show[c] = show[c].round(2)
    show["sigma"] = show["sigma"].round(4)
    show["delta_to"] = show["delta_to"].round(3)
    print(show[["border", "delivery_month", "F_from", "F_to", "fwd_spread",
                "value", "time_value", "sigma", "delta_to"]].to_string(index=False))
    print(f"\n-> {path.relative_to(ROOT)}")


def cmd_backtest(args) -> None:
    spot = install_cached_spot_loader()
    fwd = load_forwards()

    months = sorted(m for m in fwd["delivery_month"].unique()
                    if m.start_time >= spot.index.min() + pd.DateOffset(months=args.window)
                    and m.end_time <= spot.index.max())
    print(f"backtest {len(months)} delivery months: {months[0]} -> {months[-1]}, "
          f"window {args.window} months\n")

    rows = []
    for month in months:
        # Last board for THIS delivery month strictly before delivery starts.
        # Not simply max(trade_date): the workbook carries rows on non-trading
        # days where every settlement is 0 (dropped upstream), so the latest
        # calendar date is often blank.
        pre = fwd[(fwd["trade_date"] < month.start_time.tz_localize("UTC"))
                  & (fwd["delivery_month"] == month)]
        if pre.empty:
            continue
        asof = pre["trade_date"].max()
        board = pre[pre["trade_date"] == asof]

        start, end = window_bounds(month.start_time, args.window)
        caps = fit_sigmas(PRICEABLE_BORDERS, start.to_pydatetime(), end.to_pydatetime())
        priced = price_board(caps, board)
        for _, r in priced.iterrows():
            real = realised(spot, r["border"], month)
            if not real:
                continue
            rows.append({**r.to_dict(), **real, "asof": asof.date()})
        print(f"  {month}  asof {asof.date()}  priced {len(priced)}", flush=True)

    bt = pd.DataFrame(rows)
    OUT.mkdir(exist_ok=True)
    path = OUT / f"backtest_w{args.window}.csv"
    bt.to_csv(path, index=False)

    bt["err_model"] = bt["value"] - bt["realised_value"]
    bt["err_intrinsic"] = bt["intrinsic"] - bt["realised_value"]

    def agg(g):
        return pd.Series({
            "n": len(g),
            "mean_realised": g["realised_value"].mean(),
            "mean_model": g["value"].mean(),
            "mean_intrinsic": g["intrinsic"].mean(),
            "ME_model": g["err_model"].mean(),
            "MAE_model": g["err_model"].abs().mean(),
            "MAE_intrinsic": g["err_intrinsic"].abs().mean(),
            "mean_sigma": g["sigma"].mean(),
            "mean_time_value": g["time_value"].mean(),
        })

    print("\nper border:")
    print(bt.groupby("border").apply(agg, include_groups=False).round(3).to_string())
    print("\npooled:")
    print(agg(bt).round(3).to_string())
    print(f"\n-> {path.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("predict")
    p.add_argument("--window", type=int, default=12)
    p.add_argument("--asof", default=None)
    p.set_defaults(func=cmd_predict)
    b = sub.add_parser("backtest")
    b.add_argument("--window", type=int, default=12)
    b.set_defaults(func=cmd_backtest)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
