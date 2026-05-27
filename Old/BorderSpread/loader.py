#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Mar  7 21:31:14 2019

@author: marek
"""

import pandas as pd


def spot_loader(country=None, bT=None, eT=None, path=None):
    if path is None:
        path = 'C:/Users/pnace/OneDrive - Power Solutions S.R.O/Power Solutions/000 Trading/Spot model/Data/spot.csv'

    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['date'], format='%Y %m %d %H', utc=False)

    df.set_index('date', inplace=True)
    if country is None:
        country = list(df)
    if bT is None:
        bT = df.first_valid_index()
    if eT is None:
        eT = df.last_valid_index()

    try:
        df = df.loc[bT:eT, country]
    except:
        raise('Time format error datetime.date & country must be in list.')
        return list(df)
    return df


def fwd_price_loader(country=None, date=None, path=None):
    if path is None:
        path = 'C:/Users/pnace/OneDrive - Power Solutions S.R.O/Power Solutions/000 Trading/Spot model/Data/fwd_price.csv'

    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['date'], format='%m/%d/%y', utc=False)
    df.set_index('date', inplace=True)
    if date is None:
        date = df.index[-1]
    if country is None:
        country = list(df)
    price_dict = {k: v for k, v in zip(country, df.loc[date, country].values)}
    return price_dict
