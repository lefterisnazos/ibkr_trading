import time
import pandas as pd
import numpy as np
import datetime as dt
from typing import Dict, List

from sklearn.linear_model import LinearRegression

from backtesting.strategies.base import BaseStrategy
from backtesting.pos_order_trade import Position, Trade


class LinRegSigmaStrategy(BaseStrategy):
    def __init__(self, start_date: dt.datetime, end_date: dt.datetime, medium_lookback=50, long_lookback=100):
        """
        :param start_date: earliest date to include
        :param end_date: latest date
        :param medium_lookback: bars for medium LR
        :param long_lookback: bars for long LR
        """
        super(LinRegSigmaStrategy,self).__init__()
        self.start_date = start_date
        self.end_date = end_date

        self.medium_lookback = medium_lookback
        self.long_lookback = long_lookback

        self.daily_data: Dict[str, pd.DataFrame] = {}

        # final_results => {date_str: {ticker: float_pnl}}
        self.results: Dict[str, Dict[str, float]] = {}
        self.trades = []
        self.positions = []

        # For requesting intraday data
        self.next_reqID = None

        # For storing LR info => {ticker: {...}}
        self.lr_info = {}

    def get_data_from(self):
        """
        If you need an earlier start to fetch enough data for the longest lookback,
        you could do: return self.start_date - dt.timedelta(days=self.long_lookback).
        """
        return self.start_date - dt.timedelta(days=self.long_lookback)

    def prepare_data(self, app, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        """
        1) Request daily data for each ticker
        2) Filter by [self.start_date, self.end_date]
        3) Return a dict {ticker: DataFrame}
        """
        for idx, ticker in enumerate(tickers):
            app.ticker_event.clear()
            app.reqHistoricalData(
                reqId=idx,
                contract=app.usTechStk(ticker),
                endDateTime='',      # up to "now"
                durationStr='2 Y',   # or "2 Y", etc.
                barSizeSetting='1 day',
                whatToShow='TRADES',
                useRTH=1,
                formatDate=1,
                keepUpToDate=0,
                chartOptions=[]
            )
            app.ticker_event.wait()
            if app.skip:
                print(f"Skipping daily data for {ticker} due to IB error.")
                app.skip = False

        for idx, ticker in enumerate(tickers):
            df = app.data.get(idx, None)
            if df is not None and not df.empty:
                df = df.copy().reset_index(drop=True)
                df.set_index("Date", inplace=True)
                df.index = pd.to_datetime(df.index)

                # Filter by start/end
                df = df.loc[(df.index >= self.start_date) & (df.index <= self.end_date)]
                df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
                df.sort_index(inplace=True)
                self.daily_data[ticker] = df
            else:
                self.daily_data[ticker] = pd.DataFrame()

        return self.daily_data

    def run_strategy(self, app, daily_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, float]]:
        """
        For each ticker in daily_data:
          1) For each date in daily_data[ticker].index (in chronological order),
          2) Request intraday data for that date,
          3) Call simulate_intraday(...) to compute a daily PnL,
          4) Store in self.results[date_str][ticker].
        """
        self.next_reqID = 1000

        for ticker, df in daily_data.items():
            if df.empty:
                continue

            df = df.sort_index()
            dates = df.index

            # We'll do a day-by-day approach
            for date in dates:
                date_str = date.strftime("%Y-%m-%d")
                if date_str not in self.results:
                    self.results[date_str] = {}

                # 1) Recompute LR lines for this ticker up to 'date'
                #    or maybe only do this on Fridays if you prefer:
                #    if date.weekday() == 4 => do it
                self._compute_linregs_for_ticker(ticker, date)

                # 2) Request intraday data for that day
                app.ticker_event.clear()
                end_date_time = date_str + " 22:05:00 US/Eastern"
                app.reqHistoricalData(
                    reqId=self.next_reqID,
                    contract=app.usTechStk(ticker),
                    endDateTime=end_date_time,
                    durationStr='1 D',
                    barSizeSetting='5 mins',
                    whatToShow='TRADES',
                    useRTH=1,
                    formatDate=1,
                    keepUpToDate=0,
                    chartOptions=[]
                )
                app.ticker_event.wait()

                if app.skip:
                    # if IB error => skip
                    app.skip = False
                    self.results[date_str][ticker] = 0
                    self.next_reqID += 1
                    continue

                time.sleep(0.3)

                intraday_df = app.data.get(self.next_reqID, None)
                self.next_reqID += 1

                if intraday_df is None or intraday_df.empty:
                    self.results[date_str][ticker] = 0
                    continue

                intraday_df = intraday_df.reset_index(drop=True)

                # daily_row for that date
                daily_row = df.loc[date]

                # 3) Simulate intraday logic
                final_pnl = self.simulate_intraday(ticker, date_str, intraday_df, daily_row)
                self.results[date_str][ticker] = final_pnl

        return self.results

    def _compute_linregs_for_ticker(self, ticker: str, current_date: dt.datetime):
        """
        Recompute medium & long LR lines for `ticker` up to `current_date`
        using scikit-learn, computing sigma from raw Close values,
        and optionally generating future predictions.
        Store them in self.lr_info[ticker].
        """
        df = self.daily_data.get(ticker, pd.DataFrame())
        if df.empty:
            return

        # Slice up to current_date
        df_sub = df.loc[:current_date].copy()
        if len(df_sub) < self.long_lookback:
            # Not enough data => skip
            return

        # For medium
        df_med = df_sub.tail(self.medium_lookback)
        med_dict = self._fit_linreg_scikit(df_med)

        # For long
        df_long = df_sub.tail(self.long_lookback)
        long_dict = self._fit_linreg_scikit(df_long)

        # We'll store them in self.lr_info[ticker]
        self.lr_info[ticker] = {
            "medium_lr": med_dict["last_pred"],   # predicted value on last bar
            "medium_sigma": med_dict["sigma"],    # stdev of y
            "medium_future_preds": med_dict["future_preds"],

            "long_lr": long_dict["last_pred"],
            "long_sigma": long_dict["sigma"],
            "long_future_preds": long_dict["future_preds"]
        }

    def _fit_linreg_scikit(self, df_in: pd.DataFrame, days_ahead_to_predict=3) -> dict:
        """
        Fit a scikit-learn LinearRegression on df_in['Close'].
        x = 0..len-1
        Returns a dict:
          {
            "slope": ...,
            "intercept": ...,
            "sigma": stdev_of_raw_close_values,
            "last_pred": predicted_value_on_last_bar,
            "future_preds": array of predictions for the next `future_days`
          }
        """
        if len(df_in) < 2:
            return {
                "slope": None,
                "intercept": None,
                "sigma": None,
                "last_pred": None,
                "future_preds": []
            }

        # x is 0..N-1
        N = len(df_in)
        x = np.arange(N).reshape(-1, 1)
        y = df_in["Close"].values

        # Fit scikit-learn
        reg = LinearRegression()
        reg.fit(x, y)

        slope = reg.coef_[0]
        intercept = reg.intercept_

        # Sigma = stdev of the raw close values, not the residuals
        sigma = np.std(y, ddof=1)

        # predicted value for last bar
        last_pred = reg.predict([[N - 1]])[0]

        # optional future forecasts => next `future_days` bars
        x_future = np.arange(N, N + days_ahead_to_predict).reshape(-1, 1)
        future_preds = reg.predict(x_future)

        return {
            "slope": slope,
            "intercept": intercept,
            "sigma": sigma,
            "last_pred": last_pred,
            "future_preds": future_preds
        }

    def simulate_intraday(self, ticker: str, date_str: str,
                          intraday_df: pd.DataFrame, daily_row: pd.Series, volume=100) -> float:
        """
        Bar-by-bar intraday logic:
         - We have medium_lr, long_lr from self.lr_info[ticker].
         - We'll do ±2σ or ±3.5σ rules for open/close signals.
         - Return final PnL from the last bar.
        """
        lr_data = self.lr_info.get(ticker, {})
        med_lr = lr_data.get("medium_lr", None)
        med_sigma = lr_data.get("medium_sigma", None)
        long_lr = lr_data.get("long_lr", None)
        long_sigma = lr_data.get("long_sigma", None)

        if any(x is None for x in [med_lr, med_sigma, long_lr, long_sigma]):
            # No LR data => skip trades
            return 0.0

        position = None
        final_return = 0.0
        volume = 2

        for i in range(len(intraday_df)):
            bar = intraday_df.iloc[i]
            price = bar["Close"]

            # If no position => check open signals
            if position is None:
                # Buy if price < (med_lr - 2σ) AND price < (long_lr - 2σ)
                if (price < (med_lr - 2 * med_sigma)) and (price < (long_lr - 2 * long_sigma)):
                    position = Position(contract=ticker, price=price, volume=volume, side="B", timestamp=date_str)
                    open_trade = Trade(contract=ticker, price=price, volume=volume, side="B", timestamp=date_str, comment="Open long LR strategy intraday")
                    self.trades.append(open_trade)

                # Sell if price > (med_lr + 2σ) AND price > (long_lr + 2σ)
                elif (price > (med_lr + 2 * med_sigma)) and (price > (long_lr + 2 * long_sigma)):
                    position = Position(contract=ticker, price=price, volume=volume, side="S", timestamp=date_str)
                    open_trade = Trade(contract=ticker, price=price, volume=volume, side="S", timestamp=date_str, comment="Open short LR strategy intraday")
                    self.trades.append(open_trade)

            # If we have a position => check TP/SL
            if position is not None:
                if position.side == "B":
                    # Take-profit if price >= med_lr
                    if price >= med_lr:
                        close_price = med_lr
                        trade = Trade(contract=ticker, price=close_price, volume=position.volume, side="S", timestamp=date_str, comment="Close long: TP")
                        position.reduce(trade)
                        self.trades.append(trade)

                        final_return = (close_price / position.avg_price) - 1
                        position = None
                        break
                    # Stop-loss if price <= med_lr - 3.5σ
                    elif price <= (med_lr - 3.5 * med_sigma):
                        close_price = med_lr - 3.5 * med_sigma
                        trade = Trade(contract=ticker, price=close_price, volume=position.volume, side="S", timestamp=date_str, comment="Close long: SL")
                        position.reduce(trade)
                        self.trades.append(trade)

                        final_return = (close_price / position.avg_price) - 1
                        position = None
                        break
                    else:
                        # floating PnL
                        final_return = (price / position.avg_price) - 1

                else:  # short
                    # TP => price <= med_lr
                    if price <= med_lr:
                        close_price = med_lr
                        trade = Trade(contract=ticker, price=close_price, volume=position.volume, side="B", timestamp=date_str, comment="Close short: TP")
                        position.reduce(trade)
                        self.trades.append(trade)
                        final_return = 1 - (close_price / position.avg_price)
                        position = None
                        break
                    # SL => price >= med_lr + 3.5σ
                    elif price >= (med_lr + 3.5 * med_sigma):
                        close_price = med_lr + 3.5 * med_sigma
                        trade = Trade(contract=ticker, price=close_price, volume=position.volume, side="B", timestamp=date_str, comment="Close short: SL")
                        position.reduce(trade)
                        self.trades.append(trade)

                        final_return = 1 - (close_price / position.avg_price)
                        position = None
                        break
                    else:
                        # floating
                        final_return = 1 - (price / position.avg_price)

        return final_return
