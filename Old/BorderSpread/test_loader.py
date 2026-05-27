#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Mar  7 21:58:02 2019

@author: marek
"""

import datetime as dt
import loader as ld
import pandas as pd

country = ['sk', 'cz']
bT = dt.date(2018,1,1)
eT = dt.date(2019,1,1)
df = ld.spot_loader(country, bT, eT)
df.plot()

spread = pd.DataFrame()
spread['cz_sk'] = df['sk'] - df['cz']
spread.plot()