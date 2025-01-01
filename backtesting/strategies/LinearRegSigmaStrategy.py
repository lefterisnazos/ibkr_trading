import time
import pandas as pd
import numpy as np
import datetime as dt
from typing import Dict, List

from backtesting.strategies.base import BaseStrategy
from backtesting.pos_order_trade import Position, Trade


class LinRegSigmaStrategy(BaseStrategy):
    def __init__(
        self,
        start_date: dt.datetime,
        end_date: dt.datetime,
        medium_lookback=50,
        long_lookback=100
    ):
        """
        :param start_date: earliest date to include
        :param end_date: latest date
        :param medium_lookback: bars for medium LR
        :param long_lookback: bars for long LR
        """
        super().__init__()
        self.start_date = start_date
        self.end_date = end_date

        # Lookback config for the linear regressions
        self.medium_lookback = medium_lookback
        self.long_lookback = long_lookback

        # Store daily data => {ticker: DataFrame with daily bars}
        self.daily_data: Dict[str, pd.DataFrame] = {}

        # Final results => {date_str: {ticker: float_pnl}}
        self.trades = []
        self.positions = []
        self.results: Dict[str, Dict[str, float]] = {}

        # We'll store the last computed LR lines for each ticker:
        # self.lr_info[ticker] = {
        #   "med_lr": float,
        #   "med_sigma": float,
        #   "long_lr": float,
        #   "long_sigma": float
        # }
        self.lr_info = {}

    def prepare_data(self, app, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        """
        1) Request daily data for each ticker
        2) Filter by [start_date, end_date]
        3) Return a dict {ticker: DataFrame}
        """
        for idx, ticker in enumerate(tickers):
            app.ticker_event.clear()
            app.reqHistoricalData(
                reqId=idx,
                contract=app.usTechStk(ticker),
                endDateTime='',     # up to "now"
                durationStr='1 Y',  # or "2 Y" etc.
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

    def get_trade_universe_by_date(self, data: Dict[str, pd.DataFrame]) -> Dict[str, List[str]]:
        """
        For each date in the union of all daily_data indexes,
        trade all tickers that have data on that date.
        Return {date_str: [tickers]}.
        """
        all_dates = set()
        for tkr, df in data.items():
            all_dates.update(df.index)
        all_dates = sorted(list(all_dates))

        trade_universe = {}
        for d in all_dates:
            date_str = str(d.date())
            available_tickers = []
            for tkr, df in data.items():
                if d in df.index:
                    available_tickers.append(tkr)
            trade_universe[date_str] = available_tickers

        return trade_universe

    def run_strategy(self, app, daily_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, float]]:
        """
        Day-by-day iteration. For each date:
          1) If it's a Friday => recompute LR lines for each ticker that has data
          2) For each ticker => request intraday 10-min data for that date
          3) simulate_intraday(ticker, date_str, intraday_df, daily_row)

        We store final PnL in self.results[date_str][ticker].
        """
        trade_universe = self.get_trade_universe_by_date(daily_data)
        sorted_dates = sorted(trade_universe.keys())

        reqID = 10000

        for date_str in sorted_dates:
            self.results[date_str] = {}

            d_time = pd.to_datetime(date_str)
            # If Friday => recompute LR lines
            if d_time.weekday() == 4:  # 4 => Friday
                for ticker in trade_universe[date_str]:
                    self._compute_linregs_for_ticker(ticker, d_time)

            # For each ticker => request intraday data for that date
            for ticker in trade_universe[date_str]:
                app.ticker_event.clear()

                # e.g. "20241209 22:05:00 US/Eastern"
                end_date_str = date_str + " 22:05:00 US/Eastern"

                app.reqHistoricalData(
                    reqId=reqID,
                    contract=app.usTechStk(ticker),
                    endDateTime=end_date_str,
                    durationStr='1 D',
                    barSizeSetting='10 mins',   # 10-min bars
                    whatToShow='TRADES',
                    useRTH=1,
                    formatDate=1,
                    keepUpToDate=0,
                    chartOptions=[]
                )
                app.ticker_event.wait()

                if app.skip:
                    app.skip = False
                    self.results[date_str][ticker] = 0
                    reqID += 1
                    continue

                time.sleep(1)
                intraday_df = app.data.get(reqID, None)
                if intraday_df is None or intraday_df.empty:
                    self.results[date_str][ticker] = 0
                    reqID += 1
                    continue

                # Convert to datetime index if needed
                intraday_df = intraday_df.reset_index(drop=True)

                # Also retrieve the daily row for that ticker/date
                df_daily = daily_data[ticker]
                if d_time not in df_daily.index:
                    self.results[date_str][ticker] = 0
                    reqID += 1
                    continue
                daily_row = df_daily.loc[d_time]

                # Now do bar-by-bar logic
                final_pnl = self.simulate_intraday(ticker, date_str, intraday_df, daily_row)
                self.results[date_str][ticker] = final_pnl

                reqID += 1

        return self.results

    def _compute_linregs_for_ticker(self, ticker: str, current_date: dt.datetime):
        """
        Recompute medium & long LR lines for ticker up to 'current_date'
        and store them in self.lr_info[ticker].
        """
        df = self.daily_data.get(ticker, pd.DataFrame())
        df_sub = df.loc[:current_date].copy()
        if len(df_sub) < self.long_lookback:
            return  # not enough data

        # medium LR
        med_val, med_sigma = self._fit_linreg(df_sub.tail(self.medium_lookback))
        # long LR
        long_val, long_sigma = self._fit_linreg(df_sub.tail(self.long_lookback))

        self.lr_info[ticker] = {
            "medium_lr": med_val,
            "medium_sigma": med_sigma,
            "long_lr": long_val,
            "long_sigma": long_sigma
        }

    def _fit_linreg(self, sub_df: pd.DataFrame) -> (float, float):
        """
        Fit a line to 'Close' in sub_df, return (lr_value on last bar, sigma).
        """
        if len(sub_df) < 2:
            return (None, None)
        y = sub_df["Close"].values
        x = np.arange(len(y))

        slope, intercept = np.polyfit(x, y, 1)
        fitted = intercept + slope * x
        residuals = y - fitted

        sigma = residuals.std(ddof=1)
        # line value on the last bar
        lr_value = intercept + slope * (len(y) - 1)
        return (lr_value, sigma)

    def simulate_intraday(
        self,
        ticker: str,
        date_str: str,
        intraday_df: pd.DataFrame,
        daily_row: pd.Series
    ) -> float:
        """
        Bar-by-bar intraday logic:
         - We have medium_lr, long_lr, etc. from self.lr_info[ticker].
         - For each 10-min bar, see if we open/close positions
           based on LR ± 2sigma / ±3.5sigma rules.
         - Return final PnL from the last bar.
        """
        lr_data = self.lr_info.get(ticker, {})
        med_lr = lr_data.get("medium_lr", None)
        med_sigma = lr_data.get("medium_sigma", None)
        long_lr = lr_data.get("long_lr", None)
        long_sigma = lr_data.get("long_sigma", None)
        if any(x is None for x in [med_lr, med_sigma, long_lr, long_sigma]):
            # no LR data => no trades
            return 0.0

        # We'll track a single intraday position
        position = None
        final_return = 0.0

        # Bar-by-bar
        for i in range(len(intraday_df)):
            bar = intraday_df.iloc[i]
            price = bar["Close"]  # or you can use the mid or something

            # If no position => check open signals
            if position is None:
                # Buy if price < (med_lr - 2σ) AND price < (long_lr - 2σ)
                if (price < (med_lr - 2*med_sigma)) and (price < (long_lr - 2*long_sigma)):

                    position = Position(contract=ticker, price=price, volume=100, side="B", timestamp=date_str)
                    open_trade = Trade(contract=ticker, price=price, volume=100, side="B", timestamp=date_str, comment="Open long LR strategy intraday")
                    self.trades.append(open_trade)

                # Sell if price > (med_lr + 2σ) AND price > (long_lr + 2σ)
                elif (price > (med_lr + 2*med_sigma)) and (price > (long_lr + 2*long_sigma)):
                    position = Position(contract=ticker, price=price, volume=100, side="S", timestamp=date_str)
                    open_trade = Trade(contract=ticker, price=price, volume=100, side="S", timestamp=date_str, comment="Open short LR strategy intraday")
                    self.trades.append(open_trade)
                # if no open => final_return=0 up to now

            # If we have a position => check TP/SL
            if position is not None:
                if position.side == "B":  # long
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
                    elif price <= (med_lr - 3.5*med_sigma):
                        close_price = med_lr - 3.5*med_sigma
                        trade = Trade(contract=ticker, price=close_price, volume=position.volume, side="S", timestamp=date_str, comment="Close long: SL")
                        position.reduce(trade)
                        self.trades.append(trade)

                        final_return = (close_price / position.avg_price) - 1
                        position = None
                        break
                    else:
                        # floating
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
                    elif price >= (med_lr + 3.5 *med_sigma):
                        close_price = med_lr + 3.5*med_sigma
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
