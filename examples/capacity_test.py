#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Mar 23 19:39:32 2019

@author: marek
"""

import os
import sys
import datetime as dt
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # non-blocking: build figures without opening a window

# Make the spot_model package importable when run as `python examples/...`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spot_model import capacity_class as capa
from spot_model import border_class as bc
from spot_model.delivery_class import Delivery
from spot_model.loader import calc_prods


# Where historical DA prices come from:
#   'csv'    -> the static Data/spot.csv (2016-01..2019-05)
#   'entsoe' -> pulled live from the ENTSO-E Transparency Platform via the
#               plumbing client, so any zone/period ENTSO-E publishes works.
SOURCE = 'entsoe'

# at_be = Austria->Belgium capacity, be_at = the reverse. Both codes exist as
# columns in Data/spot.csv. (de_hu does not: the data has de_lu, and an
# underscore can't appear in a border endpoint anyway.) at/be have a volatile
# spread, so the fit finds a real sigma rather than 0.
border = ['at_be', 'be_at']
border_type =['implicit'] * len(border)
# Historical fit window. The csv only covers 2016-01..2019-05. For ENTSO-E,
# AT only became a standalone bidding zone on 2018-10-01 (it was part of
# DE_AT_LU before), so the at/be fit must use a post-split window.
if SOURCE == 'entsoe':
    start_date = dt.datetime(2019,1,1)
    end_date = dt.datetime(2019,12,31) - dt.timedelta(hours=1)
else:
    start_date = dt.datetime(2018,1,1)
    end_date = dt.datetime(2018,12,31) - dt.timedelta(hours=1)

# Contract specifics (only used to compute peak/base/offpeak hour ratios)
b_t = dt.datetime(2019,2,1)
e_t = dt.datetime(2019,3,1) - dt.timedelta(hours=1)
date_range = pd.date_range(b_t, e_t, freq='h')

bs_class = bc.DataBorderClass(border, border_type, start_date, end_date)
bs_class.load_data(source=SOURCE)

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
