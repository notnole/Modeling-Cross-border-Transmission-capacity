#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Mar  7 21:31:14 2019

@author: marek
"""

import pandas as pd
import numpy as np
from delivery_class import Delivery
#from Database.DB_reader import Database


def spot_loader(country_list=None, bT=None, eT=None, path=None):
    if path is None:
        path = 'C:\Data\spot_price.csv'

    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['date'], format='%Y-%m-%d %H:%M:%S', utc=False)

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


def jao_auction_loader(market=None, date=None, path=None):
    if path is None:
        path = '/Users/marek/Documents/Excel/Data/jao_auction.csv'

    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['date'], format='%m/%d/%y', utc=False)
    df.set_index('date', inplace=True)
    if date is None:
        date = df.index[-1]
    if market is None:
        market = list(df)
    price_dict = {k: v for k, v in zip(market, df.loc[date, market].values)}
    return price_dict


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

