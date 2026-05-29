#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Mar 23 19:39:32 2019

@author: marek
"""

import datetime as dt
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # non-blocking: build figures without opening a window

import capacity_class as capa
import border_class as bc
from delivery_class import Delivery
from loader import calc_prods


# at_be = Austria->Belgium capacity, be_at = the reverse. Both codes exist as
# columns in Data/spot.csv. (de_hu does not: the data has de_lu, and an
# underscore can't appear in a border endpoint anyway.) at/be have a volatile
# spread (std ~18 EUR/MWh in 2018), so the fit finds a real sigma rather than 0.
border = ['at_be', 'be_at']
border_type =['implicit'] * len(border)
# Historical data — the repo's spot.csv only covers 2016-01..2019-05.
start_date = dt.datetime(2018,1,1)
end_date = dt.datetime(2018,12,31) - dt.timedelta(hours=1)

# Contract specifics (only used to compute peak/base/offpeak hour ratios)
b_t = dt.datetime(2019,2,1)
e_t = dt.datetime(2019,3,1) - dt.timedelta(hours=1)
date_range = pd.date_range(b_t, e_t, freq='h')

bs_class = bc.DataBorderClass(border, border_type, start_date, end_date)
bs_class.load_data()

delivery_ = ['base']
data = dict()
for del_ in delivery_:
    data[del_] = bs_class.aggregate_data('M', delivery=del_)

# Hypothetical forward prices for the contract month (EUR/MWh). Set EQUAL on
# purpose: with no forward spread, any capacity value is pure option premium
# (the volatility value of max(S2 - S1, 0)), which is the whole point.
fwd_price_dict = {'at': {'base': 50.0},
                  'be': {'base': 50.0}}

fwd_price_dict = calc_prods(fwd_price_dict, date_range)

capacity = capa.ImplicitCapacity(border, delivery_)
delta_list = []
for b in border:
    capa_dict = {b: {}}
    hedge_dict = {b: {}}
    for del_ in delivery_:
        capacity.capa_fit(data[del_], del_, scaling=1)
        capacity.plot(data[del_], del_)
        p1 = fwd_price_dict[b.split('_')[0]][del_]
        p2 = fwd_price_dict[b.split('_')[1]][del_]
        price = capacity.capa_price(p1, p2, del_)
        delta = capacity.capa_delta(p1, p2, del_)
        capa_dict[b][del_] = {'value': price, 'delta': delta}
        
        print(b, ' ', del_)
        print(price)
        print(delta)
        delta_list.append(sum([abs(x) for x in delta])/2)
    # Calc delta peak base
    if len(delivery_) == 3:
        M_a = np.array([getattr(Delivery(date_range), d) for d in delivery_]) * 1
        M = M_a[:-1, :]
        hedge_dict[b] = {d: [] for d in ['base', 'peak']}
        for i in range(0, 2):
            y = (M_a[1, :].T * capa_dict[b]['peak']['delta'][i] + 
                 M_a[2, :].T * capa_dict[b]['offpeak']['delta'][i])
            delta_aux = np.linalg.solve(M @ M.T, M @ y)
            hedge_dict[b]['base'].append(delta_aux[0])
            hedge_dict[b]['peak'].append(delta_aux[1])

print(delta_list[0] * 2 - delta_list[1] * 3)
