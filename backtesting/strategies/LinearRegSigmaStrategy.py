import time
import pandas as pd
import numpy as np
import datetime as dt
from typing import Dict, List

from sklearn.linear_model import LinearRegression
from backtesting.backtester_app import *
from backtesting.ib_client import *

from backtesting.strategies.base import BaseStrategy
from backtesting.pos_order_trade import Position, Trade


class LinRegSigmaStrategy(BaseStrategy):
    def __init__(self, start_date: dt.datetime, end_date: dt.datetime, medium_lookback=20, long_lookback=40):
        """
        :param start_date: earliest date to include
        :param end_date: latest date
        :param medium_lookback: bars for medium LR
        :param long_lookback: bars for long LR
        """
        super(LinRegSigmaStrategy,self).__init__()
        self.start_date = start_date
        self.end_date = end_date
        self.ib = IBClient(port=7497, client_id=25)

        self.medium_lookback = medium_lookback
        self.long_lookback = long_lookback

        self.daily_data: Dict[str, pd.DataFrame] = {}

        # final_results => {date_str: {ticker: float_pnl}}
        self.results: Dict[str, Dict[str, float]] = {}
        self.trades = {}
        self.position = {}

        # For storing LR info => {ticker: {...}}
        self.last_train_date = None
        self.lr_info = {}

    def connect_to_ib(self):
        self.ib_client.connect()

    def disconnect_from_ib(self):
        self.ib_client.disconnect()

    def prepare_data(self, app, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        """
        1) Request daily data for each ticker
        2) Filter by [self.start_date, self.end_date]
        3) Return a dict {ticker: DataFrame}
        """
        for ticker in tickers:
            self.position[ticker] = None
            self.trades[ticker] = []

            # Example: fetch 1 year of daily data up to self.end_date
            df = self.ib_client.fetch_historical_data(symbol=ticker, end_date=self.end_date, duration_str='1 Y', bar_size='1 day')
            if df.empty:
                print(f"No daily data returned for {ticker}.")
                self.daily_data[ticker] = pd.DataFrame()
                continue

            # Filter by start_date (adjusted for lookback) and end_date
            data_from = self.get_data_from()
            df = df.loc[(df.index >= data_from) & (df.index <= self.end_date)]
            self.daily_data[ticker] = df

        return self.daily_data

    def get_data_from(self):
        """
        If you need an earlier start to fetch enough data for the longest lookback,
        you could do: return self.start_date - dt.timedelta(days=self.long_lookback).
        """
        return self.start_date - dt.timedelta(days=self.long_lookback)


    def run_strategy(self, app, daily_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, float]]:
        """
        For each ticker in daily_data:
          1) For each simulation_date in daily_data[ticker].index (in chronological order),
          2) Request intraday data for that simulation_date,
          3) Call simulate_intraday(...) to compute a daily PnL,
          4) Store in self.results[date_str][ticker].
        """
        trading_days_from_train = 0
        medium_term_results, long_term_results = {}, {}

        for ticker, df in self.daily_data.items():
            if df.empty:
                continue

            simulation_index = df[df.index >= self.start_date].index
            for simulation_date in simulation_index:

                if simulation_date not in self.results:
                    self.results[simulation_date] = {}

                if simulation_date.weekday() == 4 or simulation_index[0]== simulation_date:
                    period_df = df.loc[df.index < simulation_date]
                    medium_term_results, long_term_results = self._compute_linregs_for_ticker(ticker, period_df, simulation_date)
                    self.last_train_date = simulation_date
                    trading_days_from_train = 0

                trading_days_from_train += 1
                lr_med = medium_term_results['slope'] * (medium_term_results['data_length'] + trading_days_from_train) + medium_term_results['intercept']
                lr_long = long_term_results['slope'] * (long_term_results['data_length'] + trading_days_from_train) + long_term_results['intercept']
                sigma_med = medium_term_results['sigma']
                sigma_long = long_term_results['sigma']

                regressions_results = {'lr_med': lr_med, 'lr_long': lr_long, 'sigma_med': sigma_med, 'sigma_long': sigma_long}

                end_date_for_intraday = simulation_date.replace(hour=22, minute=5, second=0)
                intraday_df = self.ib_client.fetch_historical_data(symbol=ticker, end_date=end_date_for_intraday, duration_str='1 D', bar_size='5 mins')

                if intraday_df.empty:
                    self.results[simulation_date][ticker] = 0.0
                    continue

                # 2) Retrieve daily row if needed
                daily_row = df.loc[simulation_date]

                # 3) Run your intraday simulation
                final_pnl = self.simulate_intraday(ticker, simulation_date.date(), intraday_df, daily_row, regressions_results=regressions_results)

                # Store result
                self.results[simulation_date][ticker] = final_pnl

            return self.results

    def _get_linear_reg_values(self, term_results, simulation_date):


        lr = term_results['intercept'] + term_results['slope']*len()

    def _compute_linregs_for_ticker(self, ticker: str, period_df: pd.DataFrame, simulation_date):
        """
        Recompute medium & long LR lines for `ticker` up to `current_date`
        using scikit-learn, computing sigma from raw Close values,
        and optionally generating future predictions.
        Store them in self.lr_info[ticker].
        """

        if period_df.empty:
            return

        # For medium
        medium_window = period_df.index[-1] - dt.timedelta(days=self.medium_lookback)
        long_window = period_df.index[-1] - dt.timedelta(days=self.long_lookback)

        df_med = period_df.loc[(period_df.index>= medium_window)]
        df_long = period_df.loc[(period_df.index>= long_window)]

        med_dict = self._fit_linreg_scikit(df_med, simulation_date)
        long_dict = self._fit_linreg_scikit(df_long, simulation_date)

        # We'll store them in self.lr_info[ticker]
        self.lr_info[ticker] = {'medium': med_dict, 'long': long_dict}

        return med_dict, long_dict

    def _fit_linreg_scikit(self, df_in: pd.DataFrame, simulation_date) -> dict:
        """
        Fit a scikit-learn LinearRegression on df_in['Close'].
        x = 0..len-1
        Returns a dict:
          {
            "slope": ...,
            "intercept": ...,
            "sigma": stdev_of_raw_close_values,
            " data_length: len(df_in), so we can correctly get future predictions.

        """

        # x is 0..N-1
        N = len(df_in)
        x = np.arange(N).reshape(-1, 1)
        y = df_in["Close"].values

        reg = LinearRegression()
        reg.fit(x, y)

        slope = reg.coef_[0]
        intercept = reg.intercept_

        # Sigma = stdev of the raw close values, not the residuals
        sigma = np.std(y, ddof=1)

        return {
            "slope": slope,
            "intercept": intercept,
            "sigma": sigma,
            'data_length' : len(df_in),
            'prediction_date': simulation_date,

        }

    def simulate_intraday(self, ticker: str, date: dt.date, intraday_df: pd.DataFrame, daily_row: pd.Series, volume=1, **kwargs) -> float:
        """
        Bar-by-bar intraday logic:
         - We have medium_lr, long_lr from self.lr_info[ticker].
         - We'll do ±2σ or ±3.5σ rules for open/close signals.
         - Return final PnL from the last bar.
        """
        regressions_results = kwargs.get("regressions_results", None)
        lr_long = regressions_results.get("lr_long")
        lr_med = regressions_results.get("lr_med")
        sigma_long = regressions_results.get("sigma_long")
        sigma_med = regressions_results.get("sigma_med")

        final_return = 0.0

        for i in range(len(intraday_df)):
            bar = intraday_df.iloc[i]
            price = bar["Open"]

            # current slippage logic : fixed cost of 0.2% of price.
            virtual_buy_price = price * 1.002
            virtual_sell_price = price* 0.998

            # 1) If we have NO position for this ticker => check open signals
            if self.position[ticker] is None:
                # go Long if price < (lr_med - 2*sigma_med) AND price < (lr_long - 2*sigma_long)
                if (price < lr_med - 2 * sigma_med) and (price < lr_long - 2 * sigma_long):
                    self.position[ticker] = Position(contract=ticker, price=price, volume=volume, side="B", timestamp=date)
                    open_trade = Trade(contract=ticker, price=virtual_buy_price, volume=volume, side="B", timestamp=date, comment="Open long LR strategy intraday")
                    self.trades[ticker].append(open_trade)
                    print(open_trade)

                # go Short if price > (lr_med + 2*sigma_med) AND price > (lr_long + 2*sigma_long)
                elif (price > lr_med + 2 * sigma_med) and (price > lr_long + 2 * sigma_long):
                    self.position[ticker] = Position(contract=virtual_sell_price, price=price, volume=volume, side="S", timestamp=date)
                    open_trade = Trade(contract=ticker, price=price, volume=volume, side="S", timestamp=date, comment="Open short LR strategy intraday")
                    self.trades[ticker].append(open_trade)
                    print(open_trade)


            # 2) If we DO have a position => check TP/SL
            if self.position[ticker] is not None:
                if self.position[ticker].side == "B":

                    # Take-profit if price >= lr_med
                    if lr_med is not None and price >= lr_med:
                        trade = Trade(contract=ticker, price=virtual_sell_price, volume=self.position[ticker].volume, side="S", timestamp=date, comment="Close long: TP")
                        self.position[ticker].reduce(trade)
                        self.trades[ticker].append(trade)
                        print(trade)

                        final_return = (virtual_sell_price / self.position[ticker].avg_price) - 1
                        self.position[ticker] = None
                        break

                    # Stop-loss if price <= lr_med - 3.5*sigma_med
                    elif price <= (lr_med - 3.5 * sigma_med):
                        trade = Trade(contract=ticker, price=virtual_sell_price, volume=self.position[ticker].volume, side="S", timestamp=date, comment="Close long: SL")
                        self.position[ticker].reduce(trade)
                        self.trades[ticker].append(trade)
                        print(trade)

                        final_return = (virtual_sell_price / self.position[ticker].avg_price) - 1
                        self.position[ticker] = None
                        break
                    else:
                        # floating PnL
                        final_return = (price / self.position[ticker].avg_price) - 1

                else:  # side == "S" (short)
                    # Take-profit => price <= lr_med
                    if  price <= lr_med:
                        trade = Trade(contract=ticker, price=virtual_buy_price, volume=self.position[ticker].volume, side="B", timestamp=date, comment="Close short: TP")
                        self.position[ticker].reduce(trade)
                        self.trades[ticker].append(trade)
                        print(trade)

                        final_return = 1 - (virtual_buy_price / self.position[ticker].avg_price)
                        self.position[ticker] = None
                        break

                    # Stop-loss => price >= lr_med + 3.5*sigma_med
                    elif price >= (lr_med + 3.5 * sigma_med):
                        trade = Trade(contract=ticker, price=virtual_buy_price, volume=self.position[ticker].volume, side="B", timestamp=date, comment="Close short: SL")
                        self.position[ticker].reduce(trade)
                        self.trades[ticker].append(trade)
                        print(trade)

                        final_return = 1 - (virtual_buy_price / self.position[ticker].avg_price)
                        self.position[ticker] = None
                        break
                    else:
                        # floating
                        final_return = 1 - (price / self.position[ticker].avg_price)

        return final_return
