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
        # pandas >= 2.1: Series.dt.to_pydatetime() returns a Series, so the old
        # pd.to_datetime(...).to_frame() landed a RangeIndex and every
        # index.hour lookup below raised AttributeError. Normalise the input to
        # a DatetimeIndex instead; the masks themselves are unchanged.
        try:
            self.index = pd.DatetimeIndex(pd.to_datetime(_date_vector))
        except Exception as exc:
            raise TypeError('Input must be datetime list.') from exc
        self.date_vector = self.index.to_frame()
        self.base = self._base()
        self.peak = self._peak()
        self.offpeak = self._offpeak()

    def _base(self):
        hour_index = np.arange(0, 24)
        day_index = np.arange(0, 7)
        mask = np.logical_and(self.index.hour.isin(hour_index),
                              self.index.weekday.isin(day_index))
        return mask

    def _peak(self):
        hour_index = np.arange(8, 20)
        day_index = np.arange(0, 5)
        mask = np.logical_and(self.index.hour.isin(hour_index),
                              self.index.weekday.isin(day_index))
        return mask

    def _offpeak(self):
        mask = np.logical_and(self._base(), ~self._peak())
        return mask
