#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Mar  9 21:26:43 2019

@author: marek
"""

import numpy as np
import pandas as pd


class Delivery:
    def __init__(self, _date_vector):
        try:
            self.date_vector = pd.to_datetime(_date_vector).to_frame()
        except:
            raise('Input must be datetime list.')
        self.base = self._base()
        self.peak = self._peak()
        self.offpeak = self._offpeak()

    def _base(self):
        hour_index = np.arange(0, 24)
        day_index = np.arange(0, 7)        
        mask = (self.date_vector.index.hour.isin(hour_index) &
                self.date_vector.index.weekday.isin(day_index))
        return mask

    def _peak(self):
        hour_index = np.arange(8, 20)
        day_index = np.arange(0, 5)        
        mask = (self.date_vector.index.hour.isin(hour_index) &
                self.date_vector.index.weekday.isin(day_index))
        return mask

    def _offpeak(self):
        mask = self._base() & ~self._peak()
        return mask
