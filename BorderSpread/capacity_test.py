#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Mar 23 19:39:32 2019

@author: marek
"""

import capacity_class as capa
import border_class as bc
import datetime as dt

# all borders
borders = ['cz_sk']

for brs in borders:
    border = [brs] #['es_fr']
    border_type = ['implicit'] # ['implicit']
    start_date = dt.datetime(2017,1,1)
    end_date = dt.datetime(2019,1,1) - dt.timedelta(hours=1)

    bs_class = bc.DataBorderClass(border, border_type, start_date, end_date)
    bs_class.load_data()

    delivery_ = ['base']
    data = dict()
    for del_ in delivery_:
        data[del_] = bs_class.aggregate_data('M', delivery=del_)

    capacity = capa.ImplicitCapacity(border, delivery_)
    for del_ in delivery_:
        capacity.capa_fit(data[del_], del_)
        capacity.plot(data[del_], del_)

    F_es = 50
    F_fr = 55
    price = capacity.capa_price(F_es, F_fr, 'base')
    print('Price')
    print(price)
    delta = capacity.capa_delta(F_es, F_fr, 'base')
    print('Delta_'+border[0][:2])
    print(delta[0])
    print('Delta_'+border[0][-2:])
    print(delta[1])

    # Volatility lookup
    print('Volatility_low_mid_high')
    print(capacity.delivery['base'].values())
