#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Mar 16 11:16:13 2019

@author: marek
"""

import border_class as bc
import datetime as dt

border = ['cz_sk']
border_type = ['implicit']
start_date = dt.datetime(2018,1,1)
end_date = dt.datetime(2019,1,1) - dt.timedelta(hours=1)

bs_class = bc.DataBorderClass(border, border_type, start_date, end_date)
bs_class.load_data()

data = bs_class.aggregate_data('M', delivery='base')