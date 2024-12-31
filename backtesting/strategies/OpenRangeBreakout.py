import time
import pandas as pd
from copy import deepcopy
from backtesting.backtester_app import *
from backtesting.strategies.base import *
from typing import Dict, List, Optional
from backtesting.pos_order_trade import Order, Trade, Position
import datetime as dt

# We'll assume these come from your existing modules
# from backtester_app import ticker_event, histData, dataDataframe, usTechStk
# from your_module import BaseStrategy  # whichever path holds the BaseStrategy

class OpenRangeBreakout(BaseStrategy):
    def __init__(self, start_date, end_date):
        super().__init__()
        self.daily_data: Dict[str, pd.DataFrame] = {}
        self.results: Dict[str, Dict[str, float]] = {}
        self.trades_log = []

        # Will be set by the Backtester
        self.start_date: dt.datetime = start_date
        self.end_date: dt.datetime = end_date

    def prepare_data(self, app, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        """
        1) Request daily data for each ticker using IBKR
        2) Build 'Gap' & 'AvVol' columns
        3) Filter data based on self.start_date / self.end_date
        4) Store final DataFrames in self.daily_data
        """
        # 1) IBKR daily data request
        for idx, ticker in enumerate(tickers):
            app.ticker_event.clear()
            app.reqHistoricalData(
                reqId=idx,
                contract=app.usTechStk(ticker),
                endDateTime='',    # IB's 'latest' date
                durationStr='1 Y', # example: 1 year, or "1 M" ...
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

        # 2) Convert raw data to DataFrame & compute Gap/AvVol
        for idx, ticker in enumerate(tickers):
            df = app.data.get(idx, None)
            if df is not None and not df.empty:
                df = df.copy().reset_index(drop=True)
                df.set_index("Date", inplace=True)

                # Convert string index to datetime
                df.index = pd.to_datetime(df.index)

                # Filter by start_date / end_date
                if self.start_date and self.end_date:
                    df = df.loc[(df.index >= self.start_date) & (df.index <= self.end_date)]

                # Calculate GAP & rolling volume
                df["Gap"] = ((df["Open"] / df["Close"].shift(1)) - 1) * 100
                df["AvVol"] = df["Volume"].rolling(5).mean().shift(1)
                df.dropna(inplace=True)
                self.daily_data[ticker] = df
            else:
                print(f"No daily data found for {ticker}.")
                self.daily_data[ticker] = pd.DataFrame()

        return self.daily_data

    def get_trade_universe_by_date(self, data: Dict[str, pd.DataFrame]) -> Dict[str, List[str]]:
        """
        For each date, pick the top 5 tickers by Gap.
        Return {date_str: [tickers]}.
        """
        top_gap_by_date = {}
        all_dates = set()
        for tkr, df in data.items():
            all_dates.update(df.index.tolist())

        all_dates = sorted(list(all_dates))

        for date in all_dates:
            gap_dict = {}
            for tkr, df in data.items():
                if date in df.index:
                    gap_dict[tkr] = df.loc[date, "Gap"]
            # Sort by descending Gap
            sorted_gap = sorted(gap_dict.items(), key=lambda x: x[1], reverse=True)[:5]
            top_gap_by_date[str(date.date())] = [elem[0] for elem in sorted_gap]

        return top_gap_by_date

    def run_strategy(self, app, daily_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, float]]:
        """
        Orchestrates the intraday simulation for each date/ticker in top-gap universe.
        1) get_trade_universe_by_date(daily_data)
        2) request 5-min intraday data
        3) call simulate_intraday => final PnL
        4) return self.results
        """
        top_gap_by_date = self.get_trade_universe_by_date(daily_data)
        reqID = 10000

        for date_str, gap_list in top_gap_by_date.items():
            self.results[date_str] = {}
            for ticker in gap_list:
                app.ticker_event.clear()
                # For intraday, the endDateTime might be date_str + " 22:05:00" if we assume US/Eastern
                end_date_time = f"{date_str} 22:05:00 US/Eastern"

                app.reqHistoricalData(
                    reqId=reqID,
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
                    # If IB error => skip
                    app.skip = False
                    self.results[date_str][ticker] = 0
                    reqID += 1
                    continue

                time.sleep(2.0)
                intraday_df = app.data.get(reqID, None)

                if intraday_df is None or intraday_df.empty:
                    self.results[date_str][ticker] = 0
                    reqID += 1
                    continue

                intraday_df = intraday_df.reset_index(drop=True)

                # Retrieve the daily row
                daily_df = daily_data[ticker]
                # Convert date_str back to datetime
                dt_date = pd.to_datetime(date_str)
                if dt_date in daily_df.index:
                    daily_row = daily_df.loc[dt_date]
                else:
                    self.results[date_str][ticker] = 0
                    reqID += 1
                    continue

                final_pnl = self.simulate_intraday(ticker, date_str, intraday_df, daily_row)
                self.results[date_str][ticker] = final_pnl
                reqID += 1

        return self.results

    def simulate_intraday(self, ticker, date_str, intraday_df, daily_row) -> float:
        """
        Same bar-by-bar logic as before, using Position & Trade objects.
        """
        if intraday_df.shape[0] < 2:
            return 0.0

        # Pre-market high/low from the first bar
        hi_price = intraday_df.loc[0, "High"]
        lo_price = intraday_df.loc[0, "Low"]

        av_vol = daily_row.get("AvVol", None)
        volume_threshold = 2 * (av_vol / 78) if (av_vol is not None and not pd.isna(av_vol)) else 1e6

        position = None
        final_return = 0.0

        for i in range(1, len(intraday_df)):
            bar_prev = intraday_df.iloc[i - 1]
            bar_cur = intraday_df.iloc[i]

            # Breakout logic
            if position is None:
                if bar_prev["Volume"] > volume_threshold:
                    # Long breakout
                    if bar_cur["High"] > hi_price:
                        entry_price = self._entry_slippage(intraday_df, i, side="long")
                        position = Position(
                            contract=ticker,
                            price=entry_price,
                            volume=100,
                            side="B",
                            timestamp=date_str
                        )
                        open_trade = Trade(
                            contract=ticker,
                            price=entry_price,
                            volume=100,
                            side="B",
                            timestamp=date_str,
                            comment="Open long breakout"
                        )
                        self.trades_log.append(open_trade)

                    # Short breakout
                    elif bar_cur["Low"] < lo_price:
                        entry_price = self._entry_slippage(intraday_df, i, side="short")
                        position = Position(
                            contract=ticker,
                            price=entry_price,
                            volume=100,
                            side="S",
                            timestamp=date_str
                        )
                        open_trade = Trade(
                            contract=ticker,
                            price=entry_price,
                            volume=100,
                            side="S",
                            timestamp=date_str,
                            comment="Open short breakout"
                        )
                        self.trades_log.append(open_trade)

            if position is not None:
                if position.side == "B":  # long
                    if bar_cur["High"] >= hi_price * 1.05:
                        close_price = hi_price * 1.05
                        close_trade = Trade(
                            contract=ticker,
                            price=close_price,
                            volume=position.volume,
                            side="S",
                            timestamp=date_str,
                            comment="Close long: TP"
                        )
                        position.reduce(close_trade)
                        self.trades_log.append(close_trade)
                        final_return = (close_price / position.avg_price) - 1
                        break

                    elif bar_cur["Low"] <= lo_price:
                        close_price = lo_price
                        close_trade = Trade(
                            contract=ticker,
                            price=close_price,
                            volume=position.volume,
                            side="S",
                            timestamp=date_str,
                            comment="Close long: SL"
                        )
                        position.reduce(close_trade)
                        self.trades_log.append(close_trade)
                        final_return = (close_price / position.avg_price) - 1
                        break
                    else:
                        final_return = (bar_cur["Close"] / position.avg_price) - 1

                else:  # short
                    if bar_cur["Low"] <= lo_price * 0.95:
                        close_price = lo_price * 0.95
                        close_trade = Trade(
                            contract=ticker,
                            price=close_price,
                            volume=position.volume,
                            side="B",
                            timestamp=date_str,
                            comment="Close short: TP"
                        )
                        position.reduce(close_trade)
                        self.trades_log.append(close_trade)
                        final_return = 1 - (close_price / position.avg_price)
                        break

                    elif bar_cur["High"] >= hi_price:
                        close_price = hi_price
                        close_trade = Trade(
                            contract=ticker,
                            price=close_price,
                            volume=position.volume,
                            side="B",
                            timestamp=date_str,
                            comment="Close short: SL"
                        )
                        position.reduce(close_trade)
                        self.trades_log.append(close_trade)
                        final_return = 1 - (close_price / position.avg_price)
                        break
                    else:
                        final_return = 1 - (bar_cur["Close"] / position.avg_price)

        return final_return

    def _entry_slippage(self, intraday_df, i, side="long"):
        """
        Simple slippage model:
        80% next bar's Open + 20% next bar's High (for long)
        or Low (for short).
        """
        if i + 1 < len(intraday_df):
            next_bar = intraday_df.iloc[i + 1]
            if side == "long":
                return 0.8 * next_bar["Open"] + 0.2 * next_bar["High"]
            else:
                return 0.8 * next_bar["Open"] + 0.2 * next_bar["Low"]
        else:
            return intraday_df.iloc[i]["Close"]
