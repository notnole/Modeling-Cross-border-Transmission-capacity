#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Mar  7 21:31:14 2019

@author: marek
"""

import pandas as pd


def spot_loader(country=None, bT=None, eT=None, path=None):
    if path is None:
        path = '/Users/pnace/OneDrive/Desktop/Spot model/Data/spot.csv'

    df = pd.read_csv('/Users/pnace/OneDrive/Desktop/Spot model/Data/spot.csv')
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