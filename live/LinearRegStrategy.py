import numpy as np
import datetime as dt
from typing import List, Dict
import pandas as pd
from sklearn.linear_model import LinearRegression

from pos_order_trade_live import *
from live.ib_client_live import  *
from base import BaseStrategy  # (Assume you have a common or parent class)


# or from .BaseStrategy import BaseStrategy, if needed

class LinearRegSigmaStrategyLive:
    """
    An 'live' strategy that:
      - uses IBClientLive to get historical daily data for regression
      - sets up real-time bar/tick subscriptions (in a runner or externally)
      - places orders via ib_client.place_live_order(...)
      - relies on ib_client.on_trade_update to track positions
    """

    def __init__(self, ib_client: IBClientLive, medium_lookback=20, long_lookback=40):
        self.ib = ib_client
        self.medium_lookback = medium_lookback
        self.long_lookback = long_lookback

        # sigma multipliers or other config
        self.medium_sigma_band_open = 2
        self.medium_sigma_band_sl = 4
        self.long_sigma_band_open = 2

        # Store LR info
        self.lr_info: Dict[str, Dict[str, float]] = {}
        self.tickers = []

    def get_data_from(self, start_date: dt.datetime):
        """
        If you need an earlier start to fetch enough data for the longest lookback,
        you could do: return self.start_date - dt.timedelta(days=self.long_lookback).
        """
        return start_date - dt.timedelta(days=self.long_lookback*2)

    def prepare_data(self, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        """
        In live trading, we may fetch daily data up to 'today'
        just to compute linear regressions at the start of the session.
        You can re-call this each morning to refresh LR estimates.
        """
        # Example: fetch 1 year of daily data up to "now"
        end_date = dt.datetime.now()
        start_date = self.get_data_from(end_date) # or a smaller lookback

        for ticker in tickers:
            df = self.ib.fetch_historical_data(symbol=ticker, start_date=start_date, end_date=end_date, bar_size='1 day')
            if df.empty:
                print(f"[LiveStrategy] No daily data returned for {ticker}")
                continue
            self.lr_info[ticker] = self._compute_linregs_for_ticker(df)

    def _compute_linregs_for_ticker(self, df: pd.DataFrame):
        """
        Fit medium & long linear regressions; store slope, intercept, sigma, etc.
        """
        med_df = df.iloc[-self.medium_lookback:]
        long_df = df.iloc[-self.long_lookback:]

        med_data = self._fit_linreg_scikit(med_df['close'].values)
        long_data = self._fit_linreg_scikit(long_df['close'].values)

        return {'medium': med_data, 'long': long_data}

    def _fit_linreg_scikit(self, close_array):
        if len(close_array) < 2:
            return {'slope':0,'intercept':0,'sigma':0,'n':0}
        X = np.arange(len(close_array)).reshape(-1, 1)
        reg = LinearRegression().fit(X, close_array)
        slope = reg.coef_[0]
        intercept = reg.intercept_
        sigma = np.std(close_array, ddof=1)
        return {'slope': slope, 'intercept': intercept, 'sigma': sigma, 'n': len(close_array)}

    def on_new_bar(self, ticker: str, open_price: float, bar_time: dt.datetime, volume=100):
        """
        Called each time there's a new real-time bar for `ticker`.
        This is where we check if we open/close positions, and place orders via the IBClientLive.
        """
        if ticker not in self.lr_info:
            return

        lr_med_dict = self.lr_info[ticker]['medium']
        lr_long_dict = self.lr_info[ticker]['long']

        # Example: predict today's LR value => slope * n + intercept
        # (Some folks do slope*(n+1) if they want the next bar, etc.)
        lr_med = lr_med_dict['slope'] * lr_med_dict['n'] + lr_med_dict['intercept']
        lr_long = lr_long_dict['slope'] * lr_long_dict['n'] + lr_long_dict['intercept']
        sigma_med = lr_med_dict['sigma']
        sigma_long = lr_long_dict['sigma']


        price = open_price  # from the bar
        ticker_pos = self.ib.position.get(ticker, None)

        # Example logic:
        if ticker_pos is None:
            # Consider opening a new position:
            if (price < lr_med - self.medium_sigma_band_open*sigma_med) and (price < lr_long - self.long_sigma_band_open*sigma_long):
                print(f"[{ticker}] Opening LONG at {price}")
                self.ib.place_live_order(ticker, "BUY", volume, order_type="MKT")

            elif (price > lr_med + self.medium_sigma_band_open*sigma_med) and (price > lr_long + self.long_sigma_band_open*sigma_long):
                print(f"[{ticker}] Opening SHORT at {price}")
                self.ib.place_live_order(ticker, "SELL", volume, order_type="MKT")

        else:
            # If we have a position => check exit:
            if ticker_pos.side == "B":

                # e.g. TP or SL conditions:
                if price >= lr_med:
                    print(f"[{ticker}] Close LONG (TP) at {price}")
                    self.ib.place_live_order(ticker, "SELL", ticker_pos.volume, order_type="MKT")

                elif price <= (lr_med - self.medium_sigma_band_sl*sigma_med):
                    print(f"[{ticker}] Close LONG (SL) at {price}")
                    self.ib.place_live_order(ticker, "SELL", ticker_pos.volume, order_type="MKT")

            else:
                # short side
                if price <= lr_med:
                    print(f"[{ticker}] Close SHORT (TP) at {price}")
                    self.ib.place_live_order(ticker, "BUY", ticker_pos.volume, order_type="MKT")

                elif price >= (lr_med + self.medium_sigma_band_sl*sigma_med):
                    print(f"[{ticker}] Close SHORT (SL) at {price}")
                    self.ib.place_live_order(ticker, "BUY", ticker_pos.volume, order_type="MKT")

    def place_live_trade(self, ticker: str, side: str, qty: int, ref_price: float, order_type="MKT"):
        """
        Place an actual IB order (market or limit).
        Also immediately record a local 'Trade' with the 'intended' price
        so that PnL can be tracked if you want to keep an internal log.

        NOTE: The actual fill price might differ. We'll rely on tradeUpdateEvent
        to finalize the fill price in the self.reduce_position(...) or self.add_position(...).
        """
        # create a local "Trade" object to log the intent
        comment = f"Live {side} order for {qty} {ticker} at {ref_price}"
        # side in IB is typically "BUY" or "SELL"
        local_side = "B" if side.upper() == "BUY" else "S"
        now_ts = dt.datetime.now()

        # Place a real order with IB
        contract = self.ib.us_tech_stock(ticker)
        self.ib.place_live_order(contract, side=side.upper(),  # "BUY" or "SELL"
                                 quantity=qty, order_type=order_type,  # e.g. 'MKT'
                                 limit_price=None  # if LMT order, set a limit price
                                 )

        # We do NOT call self.add_position(...) or self.reduce_position(...) yet.
        # We let the 'fill' event trigger that in on_trade_update
        # we can optionally can store the "intent" in a separate list:  # self.trades[ticker].append(local_trade)

