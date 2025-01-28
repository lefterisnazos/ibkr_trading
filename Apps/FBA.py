import asyncio
import time
import nest_asyncio
nest_asyncio.apply()

import streamlit as st
from streamlit_autorefresh import st_autorefresh
from ib_insync import IB, Stock, util
import statsmodels.api as sm
import pandas as pd
import numpy as np


def choose_duration_str(bar_size, lookback):
    """ Return a durationStr so IB returns enough bars. Simplistic approach. """
    if bar_size == '1 day':
        # 2x margin for daily
        days_needed = lookback * 2
        return f'{days_needed} D'
    elif 'hour' in bar_size or 'min' in bar_size:
        return '4 D'
    else:
        return '10 D'


class LRSignalCalculator:
    """
    Manages a single IB() connection and provides:
      - One-shot historical data requests
      - A separate request for current price (15-min bar)
      - LR ±2σ calculations + "From Above/Below"
    """
    def __init__(self, host='127.0.0.1', port=7497, client_id=123, request_timeout=30):
        self.ib = IB()
        self.host = host
        self.port = port
        self.client_id = client_id
        self.request_timeout = request_timeout

    def _connect_if_needed(self):
        if not self.ib.isConnected():
            self.ib.connect(
                self.host, self.port,
                clientId=self.client_id,
                timeout=self.request_timeout
            )

    def _get_historical_data(self, ticker, bar_size, lookback):
        self._connect_if_needed()

        # optional short sleep to avoid pacing if user clicks quickly
        time.sleep(1.0)

        duration = choose_duration_str(bar_size, lookback)
        contract = Stock(ticker, 'SMART', 'USD')
        try:
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime='',
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow='TRADES',
                useRTH=True,
                keepUpToDate=False
            )
        except asyncio.TimeoutError:
            return pd.DataFrame()

        time.sleep(0.3)
        df = util.df(bars)
        if df is not None and not df.empty:
            df.set_index('date', inplace=True)
        else:
            df = pd.DataFrame()
        return df

    def _get_current_price(self, ticker):
        self._connect_if_needed()
        time.sleep(1.0)

        contract = Stock(ticker, 'SMART', 'USD')
        try:
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime='',
                durationStr='1 D',
                barSizeSetting='15 mins',
                whatToShow='TRADES',
                useRTH=True,
                keepUpToDate=False
            )
        except asyncio.TimeoutError:
            return None

        time.sleep(0.3)
        df = util.df(bars)
        if df is not None and not df.empty:
            return df.iloc[-1]['close']
        return None

    # ---------- LR logic ----------
    def _compute_linreg_signals_df(self, df, lookback):
        if df is None or df.empty:
            return pd.DataFrame()

        actual_lookback = min(len(df), lookback)
        if actual_lookback < 5:
            return pd.DataFrame()

        recent = df.tail(actual_lookback).copy()
        y = recent['close'].values
        X = np.arange(len(y))
        X = sm.add_constant(X)
        model = sm.OLS(y, X).fit()
        y_pred = model.predict(X)

        residuals = y - y_pred
        sigma = np.std(residuals)

        recent['lr_value'] = y_pred
        recent['lr_plus_2sigma'] = y_pred + 2.0 * sigma
        recent['lr_minus_2sigma'] = y_pred - 2.0 * sigma

        return recent

    def _find_most_recent_hit_in_ohlc(self, lr_df, use_high_low=True):
        if lr_df is None or lr_df.empty:
            return (None, None, None)

        for i in range(len(lr_df) - 1, -1, -1):
            row = lr_df.iloc[i]
            if use_high_low:
                bar_min, bar_max = row['low'], row['high']
            else:
                bar_min = min(row['open'], row['close'])
                bar_max = max(row['open'], row['close'])

            if bar_min <= row['lr_plus_2sigma'] <= bar_max:
                return ('lr_plus_2sigma', row['lr_plus_2sigma'], row.name)
            elif bar_min <= row['lr_minus_2sigma'] <= bar_max:
                return ('lr_minus_2sigma', row['lr_minus_2sigma'], row.name)
            elif bar_min <= row['lr_value'] <= bar_max:
                return ('lr_value', row['lr_value'], row.name)

        return (None, None, None)

    def _from_above_or_below(self, current_price, last_hit_value):
        if last_hit_value is None:
            return 'N/A'
        return 'From Below' if (current_price - last_hit_value) > 0 else 'From Above'

    def compute_signals(self, ticker, bar_size, short_lb, med_lb, long_lb, use_high_low=True):
        max_lb = max(short_lb, med_lb, long_lb)
        df = self._get_historical_data(ticker, bar_size, max_lb)
        if df.empty:
            return {
                'Ticker': ticker,
                'ShortSignal': 'No Data',
                'MediumSignal': 'No Data',
                'LongSignal': 'No Data'
            }

        current_price = self._get_current_price(ticker)
        if current_price is None:
            current_price = df['close'].iloc[-1]

        # Short
        short_df = self._compute_linreg_signals_df(df, short_lb)
        s_name, s_val, _ = self._find_most_recent_hit_in_ohlc(short_df, use_high_low)
        short_signal = self._from_above_or_below(current_price, s_val)

        # Medium
        med_df = self._compute_linreg_signals_df(df, med_lb)
        m_name, m_val, _ = self._find_most_recent_hit_in_ohlc(med_df, use_high_low)
        medium_signal = self._from_above_or_below(current_price, m_val)

        # Long
        long_df = self._compute_linreg_signals_df(df, long_lb)
        l_name, l_val, _ = self._find_most_recent_hit_in_ohlc(long_df, use_high_low)
        long_signal = self._from_above_or_below(current_price, l_val)

        return {
            'Ticker': ticker,
            'ShortSignal': short_signal,
            'MediumSignal': medium_signal,
            'LongSignal': long_signal
        }

# ------------------- Streamlit Part -------------------

st_autorefresh(interval=900_000, key="15min_refresh")
st.title("LR ±2σ Signals + Current Price from 15min Bar (One-Shot Historical)")

# @st.cache_resource
# def get_calculator():
#     # Return a single, cached LRSignalCalculator so we don't reconnect each run
#     return LRSignalCalculator(host='127.0.0.1', port=7497, client_id=999, request_timeout=4)
#
# calc = get_calculator()


if "calc" not in st.session_state:
    st.session_state["calc"] = LRSignalCalculator(
        host='127.0.0.1', port=7497, client_id=999, request_timeout=4
    )

calc = st.session_state["calc"]

# We store results in a session_state dictionary keyed by ticker
if "results_dict" not in st.session_state:
    st.session_state["results_dict"] = {}

bar_size = st.selectbox("Bar frequency for LR", ["5 mins", "15 mins", "1 hour", "1 day"], index=0)

col1, col2, col3 = st.columns(3)
with col1:
    short_lb = st.number_input("Short LB", min_value=5, max_value=500, value=20)
with col2:
    med_lb = st.number_input("Medium LB", min_value=5, max_value=2000, value=60)
with col3:
    long_lb = st.number_input("Long LB", min_value=5, max_value=5000, value=120)

tickers = st.multiselect("Select Tickers", ["SPY", "QQQ", "AAPL", "TSLA"], default=["SPY", "QQQ", "AAPL", "TSLA"])
range_choice = st.radio("Which candle range to check for hits?", ["High/Low", "Open/Close"])
use_high_low = (range_choice == "High/Low")

if st.button("Compute Signals"):
    for t in tickers:
        row = calc.compute_signals(t, bar_size, short_lb, med_lb, long_lb, use_high_low=use_high_low)
        # Overwrite or create the row for ticker t in session_state
        st.session_state["results_dict"][t] = row

# Convert dict of {ticker: rowDict} to a DataFrame to display
results_df = pd.DataFrame(st.session_state["results_dict"].values())
if not results_df.empty:
    st.write("### Current Signals")
    st.dataframe(results_df)
