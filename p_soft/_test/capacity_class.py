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

import loader as ld
from delivery_class import Delivery


tol = 1e-10


class Capacity(object):
    __metaclass__  = abc.ABCMeta       

    def margrabe(self, S1, S2, sigma):
        # Margrabe formula calc
        d1 = ((log(S2/S1)+ 1/2 * sigma**2)/sigma)
        d2 = d1 - sigma
        return S2*norm.cdf(d1) - S1*norm.cdf(d2)

    def delta(self, S1, S2, sigma):
        d1 = ((log(S2/S1) + 1/2 * sigma**2)/sigma)
        d2 = d1 - sigma
        return [-norm.cdf(d2), norm.cdf(d1)]

    def fit(self, S1, S2, value):
        # Data fit by Levenberg-Marquardt algorithm to margrabe function
        md = 'lm'
        def val_func(X_price, sigma):
            ret = [(self.margrabe(x[0], x[1], sigma)) for x in X_price]
            return np.array(ret)
        sigma_hat, p_cov = curve_fit(val_func, np.c_[S1, S2], value, method=md)
        return sigma_hat, p_cov[0]

    def plot(self, data, delivery_, disp=True):
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
        if disp:
            plt.show()
        return ax

    def check_state(self):
        if self._state == 0:
            raise('Fit capacity first')
    
    @abc.abstractmethod
    def asset_type(self):
        pass

    @abc.abstractmethod
    def capa_fit(self):
        pass

    @abc.abstractmethod
    def capa_price(self):
        pass

    @abc.abstractmethod
    def capa_delta(self):
        pass

    @abc.abstractmethod
    def capa_type(self):
        pass

class ImplicitCapacity(Capacity):
    def __init__(self, border, delivery):
        assert isinstance(border, list)
        self.border = border

        aux_dict = {key: np.nan for key in ['sig_low', 'sig_mid', 'sig_upp']}
        self.delivery = {key: aux_dict for key in delivery}
        self._state = 0

    @property    
    def markets(self):
        return self.border[0].split('_')

    def capa_fit(self, data, delivery_, scaling=1):
        country = self.border[0].split('_')
        S1 = data[self.border[0]][country[0]].values
        S2 = data[self.border[0]][country[1]].values
        value = data[self.border[0]]['value'].values
        # Fit data
        sigma_hat, p_cov = self.fit(S1, S2, value)
        sigma_hat[0] = sigma_hat[0]*(np.sqrt(scaling))
        self.delivery[delivery_]['sig_low'] = max(sigma_hat[0] - 1*p_cov[0], tol)
        self.delivery[delivery_]['sig_mid'] = sigma_hat[0]
        self.delivery[delivery_]['sig_upp'] = sigma_hat[0] + 1*p_cov[0]
        # Fitted
        self._state = 1
    
    def capa_price(self, S1, S2, delivery_):
        self.check_state()

        sigma = [self.delivery[delivery_][x] for x in 
                 self.delivery[delivery_].keys()]
        return [self.margrabe(S1, S2, x) for x in sigma]

    def capa_price_mid(self, S1, S2, delivery_):
        self.check_state()

        sigma = self.delivery[delivery_]['sig_mid']
        return self.margrabe(S1, S2, sigma)

    def capa_delta(self, S1, S2, delivery_):
        self.check_state()

        sigma = self.delivery[delivery_]['sig_mid']

        return self.delta(S1, S2, sigma)

    def capa_type(self):
        return 'implicit'


class CapacityDict:
    def __init__(self):
        # self.borders = []
        # self.border_types = []

        key_list = ['border', 'border_type', 'price1', 'price2', 'spread',
                    'value_low', 'value_mid', 'value_upp', 'delta1', 'delta2']
        self.__result_dict = {k: [] for k in key_list}
        self.__capacity_dict = dict()
        self.__num = 0
        self.__state = 0

    def add_capacity(self, capacity_class):
        capacity_class.check_state()

        self.__result_dict['border'].extend(capacity_class.border)
        self.__result_dict['border_type'].extend(capacity_class.capa_type())
        self.__result_dict['price1'].append(np.nan)
        self.__result_dict['price2'].append(np.nan)
        self.__result_dict['spread'].append(np.nan)
        self.__result_dict['value_low'].append(np.nan)
        self.__result_dict['value_mid'].append(np.nan)
        self.__result_dict['value_upp'].append(np.nan)
        self.__result_dict['delta1'].append(np.nan)
        self.__result_dict['delta2'].append(np.nan)

        self.__capacity_dict[capacity_class.border[0]] = capacity_class
        self.__num += 1

    def load_fwd_prices(self, path=None):
        if self.__num == 0:
            raise('Dictionary is empty. Add capacities to dictionary.')

        # Get prices
        price_dict = ld.fwd_price_loader()
        border = self.__result_dict['border']
        for i, _border in enumerate(border):
            country = _border.split('_')
            price = []
            for c in country:
                try:
                    price.append(price_dict[c])
                except(KeyError):
                    price.append(np.nan)
            self.__result_dict['price1'][i] = price[0]
            self.__result_dict['price2'][i] = price[1]
            self.__result_dict['spread'][i] = price[1] - price[0]

        self.__state = 1

    def price(self, delivery_):
        if self.__state == 0:
            raise('Load forward prices to dictionary.')

        # Get capacity price
        border = self.__result_dict['border']
        for i, _border in enumerate(border):
            S1 = self.__result_dict['price1'][i]
            S2 = self.__result_dict['price2'][i]
            price = self.__capacity_dict[_border].capa_price(S1, S2, delivery_)                                                     
            self.__result_dict['value_low'][i] = price[0]
            self.__result_dict['value_mid'][i] = price[1]
            self.__result_dict['value_upp'][i] = price[2]

            delta = self.__capacity_dict[_border].capa_delta(S1, S2, delivery_)
            self.__result_dict['delta1'][i] = delta[0]
            self.__result_dict['delta2'][i] = delta[1]

        self.__state = 2

    def sort(self, key='value_mid'):
        if self.__state < 2:
            raise('Dictionary is not fully loaded. ',
                  'Add capacities to dictionary.')

        # Sorting values based on key
        if key in self.__result_dict.keys():
            value = self.__result_dict[key]
        elif key == 'extrinsic':
            value = [(v - s) for (v, s) in zip(self.__result_dict['value_mid'],
                                               self.__result_dict['spread'])]
        else:
            raise('Unknown key value.')

        index_array = np.argsort(value)
        self.__result_dict.update((k, [v[i] for i in index_array]) for (k, v)
                                  in self.__result_dict.update.items())
        return self.__result_dict

    def plot(self, data, delivery_, disp=True):
        if self.__state < 2:
            raise('Dictionary is not fully loaded. ',
                  'Add capacities to dictionary.')

        # Loop over capacities
        border = self.__result_dict['border']
        for i, _border in enumerate(border):
            ax = self.__capacity_dict[_border].plot(data, delivery_,
                                                    disp=False)
                                                     
            # Scatter
            S1 = self.__result_dict['price1'][i]
            S2 = self.__result_dict['price2'][i]
            value = self.__result_dict['value_mid'][i]
            ax.scatter3D(S1, S2, value, cmap='Reds');
            plt.show()
