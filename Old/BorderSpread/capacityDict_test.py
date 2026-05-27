#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun May 19 13:56:08 2019

@author: marek
"""

import capacity_class as capa
import border_class as bc
import datetime as dt


border = ['es_fr', 'fr_es', 'sk_cz', 'cz_sk', 'sk_hu', 'hu_sk', 'de_fr',
          'fr_de']
n_bs = len(border)
border_type = ['implicit'] * n_bs
start_date = dt.datetime(2016,1,1)
end_date = dt.datetime(2019,1,5) - dt.timedelta(hours=1)

select_m = [1, 2, 3, 10, 11, 12]

bs_class = bc.DataBorderClass(border, border_type, start_date, end_date)
bs_class.load_data()

delivery_ = ['base']
data = dict()
for del_ in delivery_:
    data[del_] = bs_class.aggregate_data('M', delivery=del_, month_i=select_m)

capacity_dict = capa.CapacityDict()
for bs, bs_type in zip(border, border_type):
    if bs_type == 'implicit':
        capacity = capa.ImplicitCapacity([bs], delivery_)
    elif bs_type == 'explicit':
        capacity = capa.ExplicitCapacity([bs], delivery_)
    else:
        raise('Unknown capacity type.')

    # Fit capacity
    for del_ in delivery_:
        capacity.capa_fit(data[del_], del_)
    # Add to dictionary
    capacity_dict.add_capacity(capacity)
    del capacity

capacity_dict.load_fwd_prices()
for del_ in delivery_:
    capacity_dict.price(del_)
    capacity_dict.plot(data[del_], del_)