#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Mar 16 14:25:25 2019

@author: marek
"""

import abc
import numpy as np
from math import log
from scipy.stats import norm
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt
from mpl_toolkits import mplot3d

class Capacity(object):
    __metaclass__  = abc.ABCMeta

    def margrabe(self, S1, S2, sigma):
        # Margrabe formula calc
        d1 = ((log(S2/S1)+ 1/2 * sigma**2)/sigma)
        d2 = d1 - sigma
        return S2*norm.cdf(d1) - S1*norm.cdf(d2)

    def delta(self, S1, S2, sigma):
        d1 = ((log(S2/S1)+ 1/2 * sigma**2)/sigma)
        d2 = d1 - sigma
        return [norm.cdf(d1), -norm.cdf(d2)]

    def fit(self, S1, S2, value):
        # Data fit by Levenberg-Marquardt algorithm to margrabe function
        md = 'lm'
        def val_func(X_price, sigma):
            ret = [(self.margrabe(x[0], x[1], sigma)) for x in X_price]
            return np.array(ret)
        sigma_hat, p_cov = curve_fit(val_func, np.c_[S1, S2], value, method=md)
        return sigma_hat, p_cov

    def plot(self, data, delivery_):
        self.check_state()
        country = self.border[0].split('_')
        S1 = data[self.border[0]][country[0]].values
        S2 = data[self.border[0]][country[1]].values
        value = data[self.border[0]]['value'].values
        # Create figure
        self.__figure = plt.figure()
        ax = plt.axes(projection='3d')

        # Scatter
        ax.scatter3D(S1, S2, value, cmap='Greens');
        ax.set_xlabel(country[0])
        ax.set_ylabel(country[1])
        ax.set_zlabel('Capacity value')
        # Plot function
        ss1 = np.linspace(min(S1), max(S1), 50)
        ss2 = np.linspace(min(S2), max(S2), 50)
        s1, s2 = np.meshgrid(ss1, ss2)
        sigma = self.delivery[delivery_]['sig_mid']
        val = np.zeros(np.shape(s1))
        for i in np.arange(0, np.shape(s1)[0]):
            for j in np.arange(0, np.shape(s1)[1]):
                val[i][j] = self.margrabe(s1[i][j], s2[i][j], sigma)
        #val_aux = [self.margrabe(x1, x2, sigma) for (x1, x2) in zip(s1, s2)]
        #val = np.concatenate(np.array(val))
        
        ax.plot_surface(s1, s2, val, rstride=1, cstride=1,
                        cmap='viridis', edgecolor='none')
        ax.set_title('Capacity ' + self.border[0])
        ax.view_init(45, 35)
        plt.show()

    def check_state(self):
        if self._state == 0:
            raise('Fit capacity first')

    @abc.abstractmethod
    def capa_fit(self):
        pass

    @abc.abstractmethod
    def capa_price(self):
        pass

    @abc.abstractmethod
    def capa_delta(self):
        pass

class ImplicitCapacity(Capacity):
    def __init__(self, border, delivery):
        assert isinstance(border, list)
        self.border = border

        aux_dict = {key: np.nan for key in ['sig_low', 'sig_mid', 'sig_upp']}
        self.delivery = {key: aux_dict for key in delivery}
        self._state = 0

    def capa_fit(self, data, delivery_):
        country = self.border[0].split('_')
        S1 = data[self.border[0]][country[0]].values
        S2 = data[self.border[0]][country[1]].values
        value = data[self.border[0]]['value'].values
        # Fit data
        sigma_hat, p_cov = self.fit(S1, S2, value)
        self.delivery[delivery_]['sig_low'] = max(sigma_hat - 1*p_cov, 0)
        self.delivery[delivery_]['sig_mid'] = sigma_hat
        self.delivery[delivery_]['sig_upp'] = sigma_hat + 1*p_cov
        # Fitted
        self._state = 1
    
    def capa_price(self, S1, S2, delivery_):
        self.check_state()

        sigma = [self.delivery[delivery_][x] for x in 
                 self.delivery[delivery_].keys()]
        return [self.margrabe(S1, S2, x) for x in sigma]

    def capa_delta(self, S1, S2, delivery_):
        self.check_state()

        sigma = self.delivery[delivery_]['sig_mid']
        return self.delta(S1, S2, sigma)
