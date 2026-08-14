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
from zones import PRICEABLE_BORDERS, CORRIDOR_TO_BORDER   # noqa: E402

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
    if month.start_time > spot.index.max() or month.end_time < spot.index.min():
        return {}                      # delivery has not happened yet
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


# --------------------------------------------------------------------------
# bid: the actual use case. A JAO monthly auction for delivery month M closes a
# median 12 days before M starts, so the July right is bid for in mid-June.
# Everything the model reads must predate `bid_gate_closure` or the backtest is
# a lie: the forward board is the last close before the gate, and sigma is
# fitted on the 12 WHOLE months before the gate's own month (a 16-day stub
# would enter aggregate_data as a full monthly point and bias the fit).
# --------------------------------------------------------------------------
def load_auctions() -> pd.DataFrame:
    a = pd.read_csv(ROOT / "Data" / "jao_monthly.csv",
                    parse_dates=["bid_gate_closure", "delivery_start", "delivery_stop"])
    a["delivery_month"] = pd.PeriodIndex(a["delivery_month"], freq="M")
    # explicit map, not lowercase-and-replace: corridor names carry parentheses
    # (`DE(50Hz)-CZ`) and several corridors share one pricing zone pair.
    a["border"] = a["corridor"].map(CORRIDOR_TO_BORDER)
    unknown = sorted(a.loc[a["border"].isna(), "corridor"].unique())
    if unknown:
        print(f"dropping corridors with no zone-pair mapping: {unknown}")
    return a.dropna(subset=["border"])


def price_at_gate(spot, fwd, border, month, gate, window):
    """Model value of one directed right, using only pre-gate information."""
    z1, z2 = border.split("_")
    # gate.normalize(), not gate: trade_date is midnight-stamped but a day's
    # settlement is not published until that evening, so a same-day close is
    # lookahead for a gate that closes at midday.
    pre = fwd[(fwd["trade_date"] < gate.normalize()) & (fwd["delivery_month"] == month)
              & (fwd["zone"].isin([z1, z2]))]
    if pre.empty:
        return None
    asof = pre["trade_date"].max()
    board = pre[pre["trade_date"] == asof].set_index("zone")["close"]
    if z1 not in board.index or z2 not in board.index:
        return None
    F1, F2 = float(board[z1]), float(board[z2])
    if min(F1, F2) <= 0:
        return None

    start, end = window_bounds(gate.tz_convert(None) if gate.tzinfo else gate, window)
    caps = fit_sigmas([border], start.to_pydatetime(), end.to_pydatetime())
    cap, n = caps[border]
    if cap is None:
        return None
    return dict(border=border, delivery_month=str(month), gate=gate,
                fwd_asof=asof.date(), fit_start=start.date(), fit_end=end.date(),
                fit_months=n, F_from=F1, F_to=F2, fwd_spread=F2 - F1,
                intrinsic=max(F2 - F1, 0.0),
                sigma=cap.delivery["base"]["sig_mid"],
                value=cap.capa_price_mid(F1, F2, "base"),
                delta_to=cap.capa_delta(F1, F2, "base")[1])


def cmd_bid(args) -> None:
    spot = install_cached_spot_loader()
    fwd = load_forwards()
    auc = load_auctions()

    rows = []
    for _, a in auc.iterrows():
        r = price_at_gate(spot, fwd, a["border"], a["delivery_month"],
                          a["bid_gate_closure"], args.window)
        if r is None:
            continue
        r.update(corridor=a["corridor"], clearing=a["auction_price_eur_mwh"],
                 atc_mw=a["atc_mw"], allocated_mw=a["allocated_mw"],
                 bidders=a["bidder_party_count"], maint_hours=a["maintenance_hours"],
                 joint=a.get("joint_auction"))
        r.update(realised(spot, a["border"], a["delivery_month"]))
        rows.append(r)
    bids = pd.DataFrame(rows)
    bids["time_value"] = bids["value"] - bids["intrinsic"]
    OUT.mkdir(exist_ok=True)
    bids.to_csv(OUT / f"bids_w{args.window}.csv", index=False)

    # ---- the requested month, as an order table ----------------------------
    month = args.delivery or str(bids.loc[bids["clearing"].notna(), "delivery_month"].max())
    d = bids[bids["delivery_month"] == month].copy()
    if d.empty:
        raise SystemExit(f"no auctions priced for {month}; "
                         f"have {sorted(bids['delivery_month'].unique())}")
    d["bid"] = (d["value"] - args.margin).clip(lower=0).round(2)
    d["won"] = d["bid"] >= d["clearing"]
    print(f"=== delivery {month} — bid at the gate, margin {args.margin:.2f} EUR/MWh\n")
    cols = ["border", "gate", "fwd_asof", "F_from", "F_to", "value", "bid",
            "clearing", "won", "realised_value", "atc_mw", "sigma"]
    show = d[cols].copy()
    show["gate"] = show["gate"].dt.strftime("%Y-%m-%d %H:%M")
    for c in ("F_from", "F_to", "value", "clearing", "realised_value"):
        show[c] = show[c].round(2)
    show["sigma"] = show["sigma"].round(4)
    print(show.to_string(index=False))
    if d["realised_value"].notna().any():
        w = d[d["won"] & d["realised_value"].notna()]
        print(f"\nwon {len(w)} of {d['clearing'].notna().sum()}; "
              f"P&L on the won set {(w['realised_value'] - w['clearing']).sum():+.2f} "
              f"EUR/MWh summed, {(w['realised_value'] - w['clearing']).mean():+.2f} mean")

    # ---- does the rule make money? -----------------------------------------
    s = bids.dropna(subset=["clearing", "realised_value"]).copy()
    print(f"\n=== bid rule over {len(s)} cleared auctions "
          f"({s['delivery_month'].min()} -> {s['delivery_month'].max()}, "
          f"{s['corridor'].nunique()} corridors on {s['border'].nunique()} zone pairs)")
    print("assumes we are a price taker: our bid never moves the clearing price.\n")
    print(f"{'margin':>7} {'win%':>6} {'n_won':>6} {'mean cost':>10} "
          f"{'mean value':>11} {'mean P&L':>9} {'total P&L':>10} {'hit%':>6}")
    for m in args.grid:
        bid = (s["value"] - m).clip(lower=0)
        won = s[bid >= s["clearing"]]
        if won.empty:
            print(f"{m:7.2f} {0.0:6.1f} {0:6d}")
            continue
        pnl = won["realised_value"] - won["clearing"]
        print(f"{m:7.2f} {100 * len(won) / len(s):6.1f} {len(won):6d} "
              f"{won['clearing'].mean():10.2f} {won['realised_value'].mean():11.2f} "
              f"{pnl.mean():9.2f} {pnl.sum():10.1f} {100 * (pnl > 0).mean():6.1f}")
    base = s["realised_value"] - s["clearing"]
    print(f"\nbid-everything benchmark: mean P&L {base.mean():+.2f}, "
          f"total {base.sum():+.1f}, hit {100 * (base > 0).mean():.1f}% over {len(s)}")
    print(f"-> {(OUT / f'bids_w{args.window}.csv').relative_to(ROOT)}")


# --------------------------------------------------------------------------
# sheet: decision sheet for one UPCOMING delivery month. Unlike `bid`, which
# replays cleared auctions from CSV, this pulls the live board and the live
# auction envelope, so it is the thing you actually act on before a gate.
# --------------------------------------------------------------------------
# our zone code -> plumbing.eex area key. UPPERCASE: eex.short_code rejects
# lowercase with a KeyError listing the valid roots.
EEX_ZONE = {"sk": "SK", "cz": "CZ", "hu": "HU", "at": "AT", "de": "DE", "ro": "RO",
            "fr": "FR", "nl": "NL", "gr": "GR", "it": "IT", "pl": "PL"}


def live_board(zones: list[str], year: int, month: int) -> pd.DataFrame:
    """Fresh EEX monthly BASE settlements. Serialised inside plumbing.eex (429s
    are hard; the catalog says never parallelise)."""
    from plumbing import eex

    rows = []
    for z in zones:
        r = eex.month_settlement(EEX_ZONE[z], year, month)
        if r is None:
            print(f"  {z}: not listed")
            continue
        rows.append(dict(zone=z, close=r["settle"], trade_date=r["trade_date"],
                         traded=r["traded"], open_interest=r["open_interest"],
                         currency=r["currency"], short_code=r["short_code"]))
        print(f"  {z}: {r['settle']:.2f} {r['currency']} "
              f"(trade date {r['trade_date']}, OI {r['open_interest']:.0f}, "
              f"{'traded' if r['traded'] else 'no volume'})", flush=True)
    return pd.DataFrame(rows)


def live_auctions(corridors: list[str], month: str) -> pd.DataFrame:
    from plumbing.jao_auctions import JaoAuctionsClient

    c = JaoAuctionsClient()
    rows = []
    for corr in corridors:
        b = CORRIDOR_TO_BORDER[corr]
        try:
            d = c.monthly_results(corr, month)
        except Exception as exc:
            print(f"  {corr}: {type(exc).__name__} {exc}"[:110])
            continue
        if d.empty:
            continue
        if "product" in d:
            d = d[d["product"] == "BASE------"]
        for _, r in d.iterrows():
            rows.append(dict(border=b, corridor=corr,
                             gate=pd.Timestamp(r["bid_gate_closure"]),
                             clearing=r.get("auction_price_eur_mwh"),
                             atc_mw=r.get("atc_mw"),
                             maint_hours=r.get("maintenance_hours")))
    return pd.DataFrame(rows)


def cmd_sheet(args) -> None:
    month = pd.Period(args.delivery, "M")
    spot = install_cached_spot_loader()
    zones = sorted({z for b in PRICEABLE_BORDERS for z in b.split("_")}
                   & set(EEX_ZONE))

    print(f"EEX monthly BASE board for {month}:")
    board = live_board(zones, month.year, month.month)
    if board.empty:
        raise SystemExit("no EEX board")
    print(f"\nJAO monthly auctions for {month}:")
    auc = live_auctions(sorted(CORRIDOR_TO_BORDER), str(month))

    # sigma on whole months only: the gates sit inside the month before
    # delivery, so the last complete month of history is the one before that
    gate_min = auc["gate"].min() if not auc.empty else month.start_time.tz_localize("UTC")
    start, end = window_bounds(gate_min.tz_convert(None), args.window)
    print(f"\nsigma window {start.date()} -> {end.date()} ({args.window} whole months, base)"
          f"   [earliest gate {gate_min:%Y-%m-%d %H:%M} UTC]")
    caps = fit_sigmas(PRICEABLE_BORDERS, start.to_pydatetime(), end.to_pydatetime())

    px = board.set_index("zone")["close"]
    fund = fundamental_view(str(month))
    # ONE ROW PER AUCTION, not per zone pair: the German TSO-split corridors are
    # separate instruments with their own gate, ATC and clearing history even
    # though they share a price zone and therefore a value.
    rows = []
    for corr, b in sorted(CORRIDOR_TO_BORDER.items()):
        z1, z2 = b.split("_")
        cap, n = caps[b]
        if cap is None or z1 not in px or z2 not in px:
            continue
        F1, F2 = float(px[z1]), float(px[z2])
        a = auc[auc["corridor"] == corr]
        r = dict(corridor=corr, border=b, F_from=F1, F_to=F2, fwd_spread=F2 - F1,
                 intrinsic=max(F2 - F1, 0.0),
                 sigma=cap.delivery["base"]["sig_mid"],
                 value=cap.capa_price_mid(F1, F2, "base"),
                 delta_to=cap.capa_delta(F1, F2, "base")[1],
                 gate=a["gate"].iloc[0] if len(a) else pd.NaT,
                 atc_mw=a["atc_mw"].iloc[0] if len(a) else np.nan,
                 maint_hours=a["maint_hours"].iloc[0] if len(a) else np.nan,
                 cleared=(a["clearing"].notna().any() if len(a) else False),
                 auctioned=bool(len(a)))
        r["fund_p50"] = fund.get(corr, {}).get("p50", np.nan)
        r["fund_bid"] = fund.get(corr, {}).get("bid", np.nan)
        r.update(recent_clearing(corr))
        rows.append(r)
    sheet = pd.DataFrame(rows).sort_values("gate")
    sheet["margrabe_bid"] = (sheet["value"] - args.margin).clip(lower=0).round(2)
    sheet["both_ok"] = sheet["fund_bid"].notna() & (
        np.sign(sheet["margrabe_bid"]) > 0) & (sheet["fund_bid"] > 0)
    sheet["agree_bid"] = sheet[["margrabe_bid", "fund_bid"]].min(axis=1).round(2)

    OUT.mkdir(exist_ok=True)
    stamp = board["trade_date"].max()
    path = OUT / f"sheet_{month}_{stamp}.csv"
    sheet.to_csv(path, index=False)

    show = sheet.copy()
    show["gate"] = show["gate"].dt.strftime("%m-%d %H:%M")
    for c in ("F_from", "F_to", "fwd_spread", "value", "fund_p50", "fund_bid"):
        show[c] = show[c].round(2)
    show["sigma"] = show["sigma"].round(4)
    print(f"\n=== {month} decision sheet   board {stamp}   margin {args.margin:.2f}\n")
    show["wins_vs_last"] = np.where(
        show["last_clearing"].isna(), "?",
        np.where(show["agree_bid"] >= show["last_clearing"], "yes", "no"))
    print(show[["corridor", "gate", "fwd_spread", "sigma", "value", "margrabe_bid",
                "fund_p50", "fund_bid", "agree_bid", "last_clearing", "clearing_3m",
                "wins_vs_last", "atc_mw"]].to_string(index=False))
    print("\nagree_bid = min(margrabe, fundamental): the level both models clear.")
    print("wins_vs_last compares agree_bid to the most recent CLEARED month "
          "- a reference for whether the bid is even in the money, not a "
          "forecast of this auction's clearing price.")
    print("Blank fundamental = corridor/month absent from its bid book; "
          "NaN gate = no monthly auction on that corridor.")
    print(f"-> {path.relative_to(ROOT)}")


def recent_clearing(corridor: str) -> dict:
    """What this corridor actually cleared at recently — the reference for
    whether a bid will win at all. A fair value is not a bid until you know the
    level it has to beat."""
    path = ROOT / "Data" / "jao_monthly.csv"
    if not path.exists():
        return {}
    d = pd.read_csv(path)
    d = (d[(d["corridor"] == corridor) & d["auction_price_eur_mwh"].notna()]
         .sort_values("delivery_month"))
    if d.empty:
        return {}
    return dict(last_month=d["delivery_month"].iloc[-1],
                last_clearing=round(float(d["auction_price_eur_mwh"].iloc[-1]), 2),
                clearing_3m=round(float(d["auction_price_eur_mwh"].tail(3).mean()), 2))


def fundamental_view(month: str) -> dict:
    """The sibling fundamental model's p50 / bid for this delivery month."""
    local = sorted((ROOT / "Data").glob("bids_2*.csv"))
    src = local[-1] if local else (
        ROOT.parent / "capacities" / "price_model" / "outputs" / "bids_20260803.csv")
    if not src.exists():
        return {}
    print(f"fundamental view: {src.name}")
    d = pd.read_csv(src)
    d = d[d["month"] == month]
    return {r["corridor"]: dict(p50=r["p50"], bid=r["bid"])
            for _, r in d.iterrows()}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    sh = sub.add_parser("sheet")
    sh.add_argument("--delivery", required=True, help="upcoming delivery month YYYY-MM")
    sh.add_argument("--window", type=int, default=12)
    sh.add_argument("--margin", type=float, default=0.0)
    sh.set_defaults(func=cmd_sheet)
    d = sub.add_parser("bid")
    d.add_argument("--window", type=int, default=12)
    d.add_argument("--delivery", default=None, help="delivery month YYYY-MM")
    d.add_argument("--margin", type=float, default=0.0,
                   help="EUR/MWh subtracted from model value to form the bid")
    d.add_argument("--grid", type=float, nargs="*",
                   default=[-2, -1, 0, 0.5, 1, 2, 3, 5])
    d.set_defaults(func=cmd_bid)
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
