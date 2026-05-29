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
            # DatetimeIndex over the values directly. (Don't go via .to_frame():
            # since pandas 3.0, Series.dt.to_pydatetime() returns a Series whose
            # RangeIndex would otherwise replace the datetime index.)
            self.date_vector = pd.DatetimeIndex(pd.to_datetime(_date_vector))
        except Exception:
            raise ValueError('Input must be datetime list.')
        self.base = self._base()
        self.peak = self._peak()
        self.offpeak = self._offpeak()

    def _base(self):
        hour_index = np.arange(0, 24)
        day_index = np.arange(0, 7)
        mask = np.logical_and(self.date_vector.hour.isin(hour_index),
                              self.date_vector.weekday.isin(day_index))
        return mask

    def _peak(self):
        hour_index = np.arange(8, 20)
        day_index = np.arange(0, 5)
        mask = np.logical_and(self.date_vector.hour.isin(hour_index),
                              self.date_vector.weekday.isin(day_index))
        return mask

    def _offpeak(self):
        mask = np.logical_and(self._base(), ~self._peak())
        return mask
