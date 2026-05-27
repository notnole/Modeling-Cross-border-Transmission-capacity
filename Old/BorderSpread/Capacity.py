#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Mar 16 14:25:25 2019

@author: marek
"""

from abc import ABC, abstractmethod
import numpy as np

class Capacity(object):
    __metaclass__  = ABC.ABCMeta

    @abstractmethod
    def fit(self):
        pass

    @abstractmethod
    def price(self):
        pass

class ImpicitCapacity(Capacity):
    def __init__(self, border, delivery):
        self.border = border

        aux_dict = {key: np.nan for key in ['sig_low', 'sig_mid', 'sig_upp']}
        self.delivery = {key: aux_dict for key in delivery}

    