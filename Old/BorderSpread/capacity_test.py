#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Mar 23 19:39:32 2019

@author: marek
"""

import capacity_class as capa
import border_class as bc
import datetime as dt


border = ['es_fr']
border_type = ['implicit']
start_date = dt.datetime(2018,1,1)
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

