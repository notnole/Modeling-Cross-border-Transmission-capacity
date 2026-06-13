#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Net-P&L backtest of holding 1 MW of long-term transmission capacity.

For each monthly BASE auction in the JAO market-data exports:

    cost     = auction clearing price (EUR/MWh)                 [Excel export]
    realized = mean over the delivery month of max(spread, 0)   [ENTSO-E DA]
    net      = realized - cost

where the spread for border x_y is price(y) - price(x). The 'base' profile is
every hour, which is exactly the monthly base product ('Every day 00:00-24:00').

The realized leg is the value of a transmission right used optimally (flow only
when the spread is positive). ENTSO-E and JAO priceSpread give the identical
spread (verified to machine precision); ENTSO-E is used here because one pull
per zone reconstructs every border. Only fully-delivered months are scored.
"""

import datetime as dt
import os
import sys

import pandas as pd

# Make the spot_model package importable when run as `python examples/...`.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from spot_model import loader as ld

NOW = dt.datetime(2026, 6, 12)        # score only months whose delivery ended

# --- 1. Auction clearing prices (the cost side) ----------------------------
auctions = ld.jao_auction_loader()
# Keep only real, fully-delivered products: offered_mw == 0 means no LTR auction
# was held in that direction (the row is all zeros), not a free option.
auctions = auctions[(auctions['period_stop'] <= NOW) &
                    (auctions['offered_mw'] > 0)].copy()
# Some delivery months hold more than one auction session; collapse to one
# allocated-weighted clearing price per (border, month).
auctions['w'] = auctions['allocated_mw'].clip(lower=1e-9)
auctions = (auctions.assign(px_w=auctions['price_eur_mwh'] * auctions['w'])
            .groupby(['border', 'period_start'], as_index=False)
            .agg(px_w=('px_w', 'sum'), w=('w', 'sum'),
                 period_stop=('period_stop', 'first')))
auctions['price_eur_mwh'] = auctions['px_w'] / auctions['w']

# --- 2. Realized DA prices: one pull per zone, all borders built from it ----
borders = sorted(auctions['border'].unique())
zones = sorted({z for b in borders for z in b.split('_')})
win_start = auctions['period_start'].min().to_pydatetime()
win_stop = auctions['period_stop'].max().to_pydatetime()

# Historical DA prices never change, so cache the pull — re-runs are instant.
cachedir = os.path.join(ROOT, 'data', '.cache')
os.makedirs(cachedir, exist_ok=True)
cache = os.path.join(
    cachedir,
    f".da_cache_{'_'.join(zones)}_{win_start:%Y%m%d}_{win_stop:%Y%m%d}.pkl")
if os.path.exists(cache):
    prices = pd.read_pickle(cache)
else:
    prices = ld.entsoe_spot_loader(zones, win_start, win_stop)
    prices.to_pickle(cache)

# --- 3. Monthly realized base value per border ------------------------------
# base = every hour, so the monthly mean of max(price(to)-price(from), 0) is the
# realized per-MWh value of the right over that delivery month.
realized = {}
for b in borders:
    x, y = b.split('_')
    if x in prices.columns and y in prices.columns:
        realized[b] = (prices[y] - prices[x]).clip(lower=0).resample('MS').mean()

# --- 4. Join cost vs realized, compute net P&L ------------------------------
rows = []
for _, a in auctions.iterrows():
    b = a['border']
    if b not in realized:
        continue
    val = realized[b].get(pd.Timestamp(a['period_start']))
    if val is None or pd.isna(val):
        continue
    rows.append({'border': b, 'month': a['period_start'].strftime('%Y-%m'),
                 'cost': a['price_eur_mwh'], 'realized': float(val),
                 'net': float(val) - a['price_eur_mwh']})
res = pd.DataFrame(rows)

print("Net P&L of 1 MW monthly BASE LTR  (realized - auction cost, EUR/MWh)")
print(f"{len(res)} auctions, {res['border'].nunique()} borders, "
      f"{res['month'].min()}..{res['month'].max()}\n")

summary = (res.groupby('border')
              .agg(months=('net', 'size'), cost=('cost', 'mean'),
                   realized=('realized', 'mean'), net=('net', 'mean'))
              .sort_values('net', ascending=False))
print(summary.to_string(float_format=lambda x: f'{x:8.2f}'))

print(f"\nAcross all {len(res)} auctions: paid {res['cost'].mean():.2f}, "
      f"earned {res['realized'].mean():.2f}, "
      f"net {res['net'].mean():+.2f} EUR/MWh per MW-month.")
print(f"Auctions that paid off (net > 0): {(res['net'] > 0).sum()}/{len(res)}")
