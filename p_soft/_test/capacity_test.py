#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Mar 23 19:39:32 2019

@author: marek
"""

import datetime as dt
import numpy as np
import pandas as pd

import capacity_class as capa
import border_class as bc
from delivery_class import Delivery
from loader import calc_prods


border = ['de_hu', 'hu_de']
# border = ['de_be', 'be_de', 'be_nl', 'nl_be', 'nl_de', 'de_nl', 'be_fr', 'fr_be']
border_type =['implicit'] * len(border)
# Historical data
start_date = dt.datetime(2023,1,1)
end_date = dt.datetime(2023,12,31) - dt.timedelta(hours=1)

# Contract specifics
b_t = dt.datetime(2024,2,1)
e_t = dt.datetime(2024,3,1) - dt.timedelta(hours=1)
date_range = pd.date_range(b_t, e_t, freq='H')

bs_class = bc.DataBorderClass(border, border_type, start_date, end_date)
bs_class.load_data()

delivery_ = ['base']
data = dict()
for del_ in delivery_:
    data[del_] = bs_class.aggregate_data('M', delivery=del_)

fwd_price_dict = {'de': {'base': 97},
                  'fr': {'base': 90.25 - 1.5, 'peak': 137 + 1.46},
                  'at': {'base': 90.25 + 7},
                  'be': {'base': 90.25 + 1.5},
                  'nl': {'base': 90.25 + 1.5},
                  'cz': {'base': 127.5-4.75},
                  'hu': {'base': 97 + 7},
                  'si': {'base': 127.5+1.54},
                  'sk': {'base': 130.74-2.75},
                  'dke': {'base': 93},
                  'dkw': {'base': 87}}

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
