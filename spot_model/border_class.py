#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Mar  7 20:28:16 2019

@author: marek
"""

import pandas as pd
import numpy as np
import datetime as dt
from spot_model import loader as ld
from spot_model import delivery_class as dl


class DataBorderClass:
    def __init__(self, border, border_type, start_date, end_date):
        PERMITTED_TYPES = ('implicit', 'explicit')

        assert isinstance(border, list)
        assert all(elem in PERMITTED_TYPES for elem in border_type)
        assert isinstance(start_date, dt.date)
        assert isinstance(end_date, dt.date)

        self.border = border
        self.border_type = border_type
        self.start_date = start_date
        self.end_date = end_date

        data_list = ['date']
        data_list.extend(self.border)
        self.data = {key: pd.DataFrame() for key in data_list}

        self._state = 0

    def load_data(self, path_spot=None, path_auc=None, source='csv'):
        country = self.dictionary_borders()
        if source == 'entsoe':
            # Pull DA prices live from the ENTSO-E Transparency Platform via the
            # plumbing client instead of the static spot.csv.
            _data = ld.entsoe_spot_loader(country_list=country,
                                          bT=self.start_date,
                                          eT=self.end_date)
        else:
            _data = ld.spot_loader(country_list=country,
                                   bT=self.start_date,
                                   eT=self.end_date,
                                   path=path_spot)
        self.data['date'] = _data.index.to_frame()
        for (_border, _border_type) in zip(self.border, self.border_type):
            self.data[_border] = _data.loc[:, self.dictionary_borders([_border])]
            if _border_type == 'implicit':
                df_value = (self.data[_border].iloc[:, 1] -
                            self.data[_border].iloc[:, 0])
                df_value[df_value < 0] = 0
            else:
                # Not functional yet
                df_value = self.load_explicit(_border, self.start_date,
                                              self.end_date, path_auc)
            self.data[_border]['value'] = df_value

        self._state = 1
        
    def aggregate_data(self, freq, delivery='base', month_i=None, day_i=None):
        if self._state == 0:
            raise('Data not loaded yet.')
            return
        if freq in ['M', 'Q', 'Y']:
            freq += 'S'

        if month_i is None:
            month_i = np.arange(1, 13)
        if day_i is None:
            day_i = np.arange(0, 7)

        _data = self.data.copy()
        dt_vector = _data['date']['date'].dt.to_pydatetime()
        dl_mask = getattr(dl.Delivery(dt_vector), delivery)
        mask = (_data['date'].index.month.isin(month_i) & 
                _data['date'].index.weekday.isin(day_i) & dl_mask)

        # Loop over borders & aggregate data
        for _border in self.border:
            _data_aux = _data[_border][mask]
            _data[_border] = _data_aux.resample(freq).apply(np.mean)
            _data[_border].dropna(inplace=True)
        _data_aux = _data['date'][mask]
        _data['date'] = _data_aux.resample(freq).first()
        _data['date'].dropna(inplace=True)

        return _data

    def dictionary_borders(self, borders=None):
        if borders is None:
            borders = self.border

        my_dict = {}
        # Regular
        my_dict['at'] = 'at'
        my_dict['be'] = 'be'
        my_dict['bg'] = 'bg'
        my_dict['ch'] = 'ch'
        my_dict['cz'] = 'cz'
        my_dict['de'] = 'de'
        my_dict['dk1'] = 'dk1'
        my_dict['dk2'] = 'dk2'
        my_dict['ee'] = 'ee'
        my_dict['es'] = 'es'
        my_dict['fr'] = 'fr'
        my_dict['gr'] = 'gr'
        my_dict['hr'] = 'hr'
        my_dict['hu'] = 'hu'
        my_dict['itnord'] = 'itnord'
        my_dict['it'] = 'it'
        my_dict['lt'] = 'lt'
        my_dict['lv'] = 'lv'
        my_dict['nl'] = 'nl'
        my_dict['ro'] = 'ro'
        my_dict['si'] = 'si'
        my_dict['sk'] = 'sk'
        my_dict['sr'] = 'sr'
        my_dict['dkw'] = 'dkw'
        my_dict['dke'] = 'dke'

        country = []
        for _border in borders:
            country_aux = [my_dict[x] for x in _border.split('_')]
            country.extend(country_aux)
            del country_aux
        return pd.Series(country).drop_duplicates().tolist()
