#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Mar  7 21:31:14 2019

@author: marek
"""

import os
import sys
import glob
import pandas as pd
import numpy as np
from spot_model.delivery_class import Delivery
#from Database.DB_reader import Database


# Repo's spot data: <repo_root>/data/spot.csv, resolved relative to this file
# so it works regardless of the current working directory. This is the offline
# fallback for source='csv'; historical DA prices are normally pulled live
# (entsoe_spot_loader).
_DEFAULT_SPOT = os.path.join(os.path.dirname(__file__), '..',
                             'data', 'spot.csv')


# ---------------------------------------------------------------------------
# Live DA prices via the ClaudeWorkspace `plumbing.entsoe` client.
#
# This is the alternative to the static spot.csv: instead of a frozen file we
# pull any country's day-ahead clearing prices straight from the ENTSO-E
# Transparency Platform, so the model can be priced against any series/period
# that ENTSO-E publishes. The plumbing package lives in a sibling project, so
# we add it to sys.path on first use. Override the location with the
# CLAUDE_WORKSPACE env var if your checkout lives elsewhere.
# ---------------------------------------------------------------------------
_DEFAULT_WORKSPACE = r'C:\Users\noelp\PycharmProjects\ClaudeWorkspace'

# Model country code (as used in border strings / dictionary_borders) -> the
# ENTSO-E bidding-zone Area name accepted by the entsoe-py client. Border
# endpoints can't contain '_', so the model uses 'de' / 'itnord' where ENTSO-E
# uses 'DE_LU' / 'IT_NORD'.
_ENTSOE_AREA = {
    'at': 'AT', 'be': 'BE', 'cz': 'CZ',
    'de': 'DE_LU', 'de_lu': 'DE_LU',
    'hu': 'HU', 'sk': 'SK', 'ro': 'RO', 'fr': 'FR', 'nl': 'NL', 'pl': 'PL',
    'si': 'SI', 'hr': 'HR', 'ch': 'CH', 'es': 'ES',
    'it': 'IT_NORD', 'itnord': 'IT_NORD', 'it_nord': 'IT_NORD',
    'dk1': 'DK_1', 'dk2': 'DK_2',
    'ee': 'EE', 'lv': 'LV', 'lt': 'LT',
    'bg': 'BG', 'gr': 'GR',
    'rs': 'RS', 'sr': 'RS',
}


def _get_entsoe_client(workspace_path=None):
    """Import and instantiate the plumbing EntsoeClient (token from .env)."""
    ws = workspace_path or os.environ.get('CLAUDE_WORKSPACE') or _DEFAULT_WORKSPACE
    if ws not in sys.path:
        sys.path.insert(0, ws)
    from plumbing.entsoe import EntsoeClient
    return EntsoeClient()


def entsoe_spot_loader(country_list=None, bT=None, eT=None,
                       tz='Europe/Brussels', workspace_path=None, client=None):
    """Drop-in replacement for `spot_loader` that pulls live DA prices.

    Returns the same shape spot_loader does: a DataFrame with a naive hourly
    DatetimeIndex named 'date' and one column per requested model country code,
    so DataBorderClass can consume it unchanged.

    `country_list` is required (e.g. ['at', 'be']). `bT`/`eT` are naive
    datetimes in local market time. `tz` is the single wall clock all zones are
    expressed in (CET, matching the original spot.csv and Delivery's local
    peak hours 8-19); pass a `client` to reuse one EntsoeClient across calls.
    """
    if country_list is None:
        raise ValueError("entsoe_spot_loader needs an explicit country_list, "
                         "e.g. ['at', 'be'].")
    if client is None:
        client = _get_entsoe_client(workspace_path)

    series = {}
    for code in country_list:
        area = _ENTSOE_AREA.get(code.lower())
        if area is None:
            raise KeyError(f"No ENTSO-E area mapping for country code {code!r}. "
                           f"Add it to _ENTSOE_AREA in loader.py.")
        df = client.day_ahead_prices(area, bT, eT)
        series[code] = df['price_eur_mwh']

    out = pd.concat(series, axis=1)
    out.columns = list(series.keys())

    # ENTSO-E hands back a tz-aware UTC index. The model works in local
    # wall-clock time (Delivery peak = local 8-19), as the original spot.csv
    # did, so convert every zone to one CET clock and drop the tz.
    out = out.tz_convert(tz).tz_localize(None)

    # Collapse to hourly means (newer ENTSO-E data can be 15-min resolution).
    out = out.resample('h').mean()
    out.index.name = 'date'

    if bT is not None or eT is not None:
        out = out.loc[bT:eT]
    return out


# ---------------------------------------------------------------------------
# Realized cross-border spreads via the JAO Publication Tool (Core CCR).
#
# For a historical backtest we need the spread the market actually realized,
# not just spot levels. JAO's `priceSpread` endpoint publishes the signed DA
# price spread per directional border. Its sign convention is INVERTED relative
# to "price(A) - price(B)": JAO `border_X_Y == price(Y) - price(X)`, which is
# exactly the model's signed spread for border 'x_y' (from=x -> to=y, value =
# max(price(y) - price(x), 0)). Verified to machine precision against ENTSO-E.
# So the JAO column maps to the model border with the SAME ordering, no flip.
#
# Coverage: Core CCR zones only, and only from 2022-06-08 (Core flow-based
# go-live). Italy/non-Core borders are not in this dataset.
# ---------------------------------------------------------------------------

# Model country code -> JAO Core bidding-zone code. Note JAO uses 'DE' (not the
# ENTSO-E 'DE_LU') and 'DK1'/'DK2'.
_JAO_ZONE = {
    'at': 'AT', 'be': 'BE', 'cz': 'CZ',
    'de': 'DE', 'de_lu': 'DE',
    'fr': 'FR', 'hr': 'HR', 'hu': 'HU', 'nl': 'NL', 'pl': 'PL', 'ro': 'RO',
    'si': 'SI', 'sk': 'SK', 'dk1': 'DK1', 'dk2': 'DK2',
}


def _get_jao_client(workspace_path=None):
    """Import and instantiate the plumbing JaoClient (anonymous, or
    JAO_API_KEY from .env if present)."""
    ws = workspace_path or os.environ.get('CLAUDE_WORKSPACE') or _DEFAULT_WORKSPACE
    if ws not in sys.path:
        sys.path.insert(0, ws)
    from plumbing.jao import JaoClient
    return JaoClient()


def jao_spread_loader(border_list=None, bT=None, eT=None,
                      tz='Europe/Brussels', workspace_path=None,
                      client=None, dataset='core'):
    """Pull realized directional DA price spreads from JAO `priceSpread`.

    Returns a DataFrame with a naive hourly DatetimeIndex named 'date' (single
    CET wall clock, matching the rest of the model) and one column per model
    border string (e.g. 'sk_cz'). Each column is the *signed* spread
    price(to) - price(from); take max(., 0) for the realized per-MW capacity
    payoff. `border_list` is required (str or list). Core CCR borders only,
    data from 2022-06-08 onward.
    """
    if border_list is None:
        raise ValueError("jao_spread_loader needs an explicit border_list, "
                         "e.g. ['sk_cz'].")
    if isinstance(border_list, str):
        border_list = [border_list]
    if client is None:
        client = _get_jao_client(workspace_path)

    df = client.get('priceSpread', bT, eT, dataset=dataset)
    if df.empty:
        raise ValueError("JAO priceSpread returned no rows. Core flow-based "
                         "data starts 2022-06-08 — check the requested window.")

    # tz-aware UTC -> one CET wall clock, naive (match spot.csv / the model).
    df = df.tz_convert(tz).tz_localize(None)

    out = {}
    for border in border_list:
        x, y = border.split('_')
        zx, zy = _JAO_ZONE.get(x.lower()), _JAO_ZONE.get(y.lower())
        if zx is None or zy is None:
            raise KeyError(f"No JAO Core zone mapping for border {border!r}. "
                           f"JAO priceSpread covers Core CCR zones only.")
        col = f"border_{zx}_{zy}"
        if col not in df.columns:
            raise KeyError(f"JAO priceSpread has no column {col!r} for border "
                           f"{border!r}. The border may be outside Core or only "
                           f"published in the other direction — inspect columns.")
        out[border] = df[col]

    spread = pd.concat(out, axis=1)
    spread.columns = list(out.keys())
    spread = spread.resample('h').mean()
    spread.index.name = 'date'
    if bT is not None or eT is not None:
        spread = spread.loc[bT:eT]
    return spread


def delivery_mean(df, delivery='base'):
    """Mean of each column over the hours of a delivery profile.

    `df` must have an hourly (naive) DatetimeIndex. Returns {column: mean}.
    Used for backtests: feed a spread DataFrame clipped at 0 to get the
    realized per-MW capacity value, or raw zone prices to get the period
    forward proxy."""
    dt_vector = df.index.to_pydatetime()
    mask = getattr(Delivery(dt_vector), delivery)
    masked = df[mask]
    return {col: float(masked[col].mean()) for col in masked.columns}


def spot_loader(country_list=None, bT=None, eT=None, path=None):
    if path is None:
        path = _DEFAULT_SPOT

    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['date'], format='%Y %m %d %H', utc=False)

    df.set_index('date', inplace=True)
    if country_list is None:
        country_list = list(df)
    if bT is None:
        bT = df.first_valid_index()
    if eT is None:
        eT = df.last_valid_index()

    try:
        df = df.loc[bT:eT, country_list]
    except:
        raise('Time format error datetime.date & country must be in list.')
        return list(df)
    return df

# def spot_loader(country_list=None, d_range=365,
#                 bT=None, eT=None, desc=False):
#     db_reader = Database()
#     if bT==None:
#         pass
#     else:
#         bT = bT.strftime('%Y-%m-%d')
#     if eT==None:
#         pass
#     else:
#         eT = eT.strftime('%Y-%m-%d')
#     df = db_reader.getSpotPriceData(country_list,
#                                     range=d_range,
#                                     _from=bT,
#                                     _to=eT,
#                                     desc=desc)
#     df.index.name = 'date'
#     return df

# def spot_loader(country=None, bT=None, eT=None, path=None):
#     if path is None:
#         path = 'C:/Users/krajcovic/Documents/Trading/Data/Price/EEX/Spot/spot.txt'

#     df = pd.read_csv(path)
#     df['date'] = pd.to_datetime(df['date'], format='%Y %m %d %H', utc=False)

#     df.set_index('date', inplace=True)
#     if country is None:
#         country = list(df)
#     if bT is None:
#         bT = df.first_valid_index()
#     if eT is None:
#         eT = df.last_valid_index()

#     try:
#         df = df.loc[bT:eT, country]
#     except:
#         raise('Time format error datetime.date & country must be in list.')
#         return list(df)
#     return df


def fwd_price_loader(country=None, date=None, path=None):
    if path is None:
        path = '/Users/marek/Documents/Excel/Data/fwd_price.csv'

    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['date'], format='%m/%d/%y', utc=False)
    df.set_index('date', inplace=True)
    if date is None:
        date = df.index[-1]
    if country is None:
        country = list(df)
    price_dict = {k: v for k, v in zip(country, df.loc[date, country].values)}
    return price_dict


# ---------------------------------------------------------------------------
# JAO long-term-rights auction clearing prices (the capacity COST side).
#
# JAO does not publish LTR auction clearing prices through the Publication Tool
# API; they live on the separate auctions.jao.eu system (token-gated). Rather
# than wire that API, we read the manual "JAO market data export" spreadsheets
# dropped in the repo root (JAO_marketdata_export*.xlsx). Each row is one
# monthly auction for one directional border: the clearing Price (EUR/MWh) plus
# offered / requested / allocated capacity. Pair the price with the realized
# spread value (jao_spread_loader / entsoe_spot_loader) for a net-P&L backtest.
#
# openpyxl (and therefore pandas) can't open these files — their stylesheet is
# malformed — so we read the worksheet straight out of the .xlsx zip/XML.
# ---------------------------------------------------------------------------
_DEFAULT_AUCTION_GLOB = os.path.join(os.path.dirname(__file__), '..', 'data',
                                     'jao', 'JAO_marketdata_export*.xlsx')

_XLSX_NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def _xlsx_col_index(ref):
    """'A' -> 1, 'Z' -> 26, 'AA' -> 27 (Excel column letters to 1-based index)."""
    n = 0
    for ch in ref:
        n = n * 26 + (ord(ch) - 64)
    return n


def _read_xlsx_rows(path):
    """Read the first worksheet of an .xlsx as a list of header-keyed dicts,
    going through the zip/XML directly (openpyxl chokes on the JAO exports'
    malformed stylesheet)."""
    import zipfile
    import re
    import xml.etree.ElementTree as ET

    z = zipfile.ZipFile(path)
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        sroot = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in sroot.findall(_XLSX_NS + 'si'):
            shared.append(''.join(t.text or '' for t in si.iter(_XLSX_NS + 't')))

    root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    matrix = []
    for row in root.iter(_XLSX_NS + 'row'):
        cells = {}
        for c in row.findall(_XLSX_NS + 'c'):
            col = re.match(r'[A-Z]+', c.get('r')).group()
            v = c.find(_XLSX_NS + 'v')
            if v is None:
                continue
            cells[col] = shared[int(v.text)] if c.get('t') == 's' else v.text
        matrix.append(cells)
    if not matrix:
        return []

    cols = sorted({k for r in matrix for k in r}, key=_xlsx_col_index)
    header = [matrix[0].get(c, '') for c in cols]
    out = []
    for r in matrix[1:]:
        out.append({header[i]: r.get(cols[i]) for i in range(len(cols))})
    return out


def jao_auction_loader(path=None, border_list=None):
    """Load JAO LTR monthly-auction clearing prices from the market-data export
    spreadsheets (JAO_marketdata_export*.xlsx in the repo root).

    Returns a DataFrame, one row per (border, delivery month), with columns:
    border (model 'xx_yy' form), period_start, period_stop, timetable,
    price_eur_mwh (the auction clearing price = capacity cost), and the
    offered / requested / allocated MW. Optionally restrict to `border_list`
    (model border strings). Multiple export files are concatenated."""
    if path is None:
        paths = sorted(glob.glob(_DEFAULT_AUCTION_GLOB))
    elif isinstance(path, str):
        paths = [path]
    else:
        paths = list(path)
    if not paths:
        raise FileNotFoundError(
            "No JAO auction export found. Expected JAO_marketdata_export*.xlsx "
            "in the repo root, or pass path=...")

    frames = [pd.DataFrame(_read_xlsx_rows(p)) for p in paths]
    df = pd.concat([f for f in frames if not f.empty], ignore_index=True)

    def col(sub):
        for c in df.columns:
            if sub.lower() in c.lower():
                return c
        raise KeyError(f"No column matching {sub!r} in {list(df.columns)}")

    out = pd.DataFrame({
        'border': df[col('Border')].str.replace('-', '_').str.lower(),
        'period_start': pd.to_datetime(df[col('period start')], format='%d/%m/%Y'),
        'period_stop': pd.to_datetime(df[col('period stop')], format='%d/%m/%Y'),
        'timetable': df[col('TimeTable')],
        'offered_mw': pd.to_numeric(df[col('OfferedCapacity')], errors='coerce'),
        'requested_mw': pd.to_numeric(df[col('requested capacity')], errors='coerce'),
        'price_eur_mwh': pd.to_numeric(df[col('Price')], errors='coerce'),
        'allocated_mw': pd.to_numeric(df[col('allocated capacity')], errors='coerce'),
    })
    if border_list is not None:
        if isinstance(border_list, str):
            border_list = [border_list]
        out = out[out['border'].isin(border_list)]
    return out.sort_values(['border', 'period_start']).reset_index(drop=True)


def calc_prods(fwd_dict, date_vector):
    del_list = ['base', 'peak', 'offpeak']
    out_dict = {m: {d: np.nan for d in del_list} for m in fwd_dict.keys()}
    mask_dict = {d: getattr(Delivery(date_vector), d) for d in del_list}
    rat_dict = {d: sum(mask_dict[d]) / len(mask_dict[d]) for d in del_list}
    for m in fwd_dict.keys():
        p_aux_list = [np.nan if d not in fwd_dict[m].keys() else fwd_dict[m][d]
                      for d in del_list]
        nan_list = [np.isnan(v) for v in p_aux_list]
        out_dict[m].update({d: v for d, v in zip(del_list, p_aux_list)})
        if sum(nan_list) == 1:
            d_c = [d for d, v in zip(del_list, nan_list) if v]
            d_v = [d for d, v in zip(del_list, nan_list) if not v]
            if d_c[0] == 'base':
                out_dict[m][d_c[0]] = ((rat_dict[d_v[0]] * out_dict[m][d_v[0]] +
                                        rat_dict[d_v[1]] * out_dict[m][d_v[1]]) /
                                       rat_dict[d_c[0]])
            else:
                out_dict[m][d_c[0]] = ((rat_dict[d_v[0]] * out_dict[m][d_v[0]] -
                                        rat_dict[d_v[1]] * out_dict[m][d_v[1]]) /
                                       rat_dict[d_c[0]])
        elif sum(nan_list) == 0:
            op = ((rat_dict['base'] * out_dict[m]['base'] +
                   rat_dict['peak'] * out_dict[m]['peak']) /
                  rat_dict['offpeak'])
            if op != out_dict[m]['offpeak']:
                out_dict[m]['offpeak'] = op
                print('Warning offpeak wrong input', m)
    return out_dict

