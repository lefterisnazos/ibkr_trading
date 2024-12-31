import time
import pandas as pd
from copy import deepcopy
from backtesting.backtester_app import *
from backtesting.strategies.base import *
from typing import Dict, List, Optional
from backtesting.pos_order_trade import Order, Trade, Position

# We'll assume these come from your existing modules
# from backtester_app import ticker_event, histData, dataDataframe, usTechStk
# from your_module import BaseStrategy  # whichever path holds the BaseStrategy

class OpenRangeBreakout(BaseStrategy):
    def __init__(self):
        super().__init__()
        self.daily_data: Dict[str, pd.DataFrame] = {}  # {ticker: DataFrame with daily bars}
        self.results: Dict[str, Dict[str, float]] = {} # {date: {ticker: final_pnl}}
        self.trades_log = []                           # list of Trade objects

    def prepare_data(self, app: BacktesterApp, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        """
        1) Request daily data from IBKR for each ticker
        2) Compute 'Gap' & 'AvVol' columns
        3) Store the final DataFrames in self.daily_data
        4) Return the same dictionary
        """
        for idx, ticker in enumerate(tickers):
            app.ticker_event.clear()
            app.reqHistoricalData(
                reqId=idx,
                contract=usTechStk(ticker),
                endDateTime='',
                durationStr='1 M',
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

        # Convert the collected data to DataFrame & compute Gap, AvVol
        for idx, ticker in enumerate(tickers):
            df = app.data.get(idx, None)
            if df is not None and not df.empty:
                df = df.copy().reset_index(drop=True)
                df.set_index("Date", inplace=True)
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
        # gather all dates from each ticker's DataFrame
        all_dates = set()
        for tkr, df in data.items():
            all_dates.update(df.index.tolist())

        all_dates = sorted(list(all_dates))

        for date in all_dates:
            gap_dict = {}
            for tkr, df in data.items():
                if date in df.index:
                    gap_dict[tkr] = df.loc[date, "Gap"]
            # sort by descending Gap
            sorted_gap = sorted(gap_dict.items(), key=lambda x: x[1], reverse=True)[:5]
            top_gap_by_date[date] = [elem[0] for elem in sorted_gap]

        return top_gap_by_date

    def run_strategy(self, app: BacktesterApp, daily_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, float]]:
        """
        Orchestrates the intraday backtest:
          1) get the top-gap tickers by date
          2) for each date/ticker => request 5-min intraday
          3) call simulate_intraday(...) => final PnL
          4) store results
        """
        top_gap_by_date = self.get_trade_universe_by_date(daily_data)
        reqID = 10000

        for date, gap_list in top_gap_by_date.items():
            self.results[date] = {}
            for ticker in gap_list:
                # request intraday data
                app.ticker_event.clear()
                app.reqHistoricalData(
                    reqId=reqID,
                    contract=usTechStk(ticker),
                    endDateTime=date + " 22:05:00 US/Eastern",
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
                    self.results[date][ticker] = 0
                    reqID += 1
                    continue

                time.sleep(2.0)  # small buffer
                intraday_df = app.data.get(reqID, None)

                if intraday_df is None or intraday_df.empty:
                    self.results[date][ticker] = 0
                    reqID += 1
                    continue

                intraday_df = intraday_df.reset_index(drop=True)

                # get the daily row for this date/ticker
                daily_row = daily_data[ticker].loc[date]
                final_pnl = self.simulate_intraday(ticker, date, intraday_df, daily_row)
                self.results[date][ticker] = final_pnl
                reqID += 1

        return self.results

    def simulate_intraday(self, ticker: str, date: str, intraday_df: pd.DataFrame, daily_row: pd.Series) -> float:
        """
        The bar-by-bar open range breakout logic using Position & Trade objects
        (mirroring your original 'serial' logic but organized).
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
            volume = 1

            # If no position => check breakout (long or short)
            if position is None:
                if bar_prev["Volume"] > volume_threshold:
                    # potential long breakout
                    if bar_cur["High"] > hi_price:
                        entry_price = self._entry_slippage(intraday_df, i, side="long")
                        position = Position(
                            contract=ticker,
                            price=entry_price,
                            volume=volume,
                            side="B",   # "B" => buy/long
                            timestamp=date
                        )
                        # log opening trade
                        open_trade = Trade(
                            contract=ticker,
                            price=entry_price,
                            volume=volume,
                            side="B",
                            timestamp=date,
                            comment="Open long breakout"
                        )
                        self.trades_log.append(open_trade)

                    # potential short breakout
                    elif bar_cur["Low"] < lo_price:
                        entry_price = self._entry_slippage(intraday_df, i, side="short")
                        position = Position(
                            contract=ticker,
                            price=entry_price,
                            volume=volume,
                            side="S",   # "S" => sell/short
                            timestamp=date
                        )
                        # log opening trade
                        open_trade = Trade(
                            contract=ticker,
                            price=entry_price,
                            volume=volume,
                            side="S",
                            timestamp=date,
                            comment="Open short breakout"
                        )
                        self.trades_log.append(open_trade)

            # If we have a position => check TP/SL
            if position is not None:
                if position.side == "B":  # long
                    # 5% take profit => if bar_cur["High"] >= hi_price * 1.05
                    if bar_cur["High"] >= hi_price * 1.05:
                        close_price = hi_price * 1.05
                        close_trade = Trade(
                            contract=ticker,
                            price=close_price,
                            volume=position.volume,
                            side="S",  # offset the long
                            timestamp=date,
                            comment="Close long: TP"
                        )
                        position.reduce(close_trade)
                        self.trades_log.append(close_trade)

                        final_return = (close_price / position.avg_price) - 1
                        if position.volume == 0:
                            position = None
                        break

                    # stop-loss => if bar_cur["Low"] <= lo_price
                    elif bar_cur["Low"] <= lo_price:
                        close_price = lo_price
                        close_trade = Trade(
                            contract=ticker,
                            price=close_price,
                            volume=position.volume,
                            side="S",
                            timestamp=date,
                            comment="Close long: SL"
                        )
                        position.reduce(close_trade)
                        self.trades_log.append(close_trade)

                        final_return = (close_price / position.avg_price) - 1
                        if position.volume == 0:
                            position = None
                        break
                    else:
                        # floating PnL
                        final_return = (bar_cur["Close"] / position.avg_price) - 1

                else:  # short
                    # 5% take profit => if bar_cur["Low"] <= lo_price * 0.95
                    if bar_cur["Low"] <= lo_price * 0.95:
                        close_price = lo_price * 0.95
                        close_trade = Trade(
                            contract=ticker,
                            price=close_price,
                            volume=position.volume,
                            side="B",
                            timestamp=date,
                            comment="Close short: TP"
                        )
                        position.reduce(close_trade)
                        self.trades_log.append(close_trade)

                        final_return = 1 - (close_price / position.avg_price)
                        if position.volume == 0:
                            position = None
                        break

                    # stop-loss => if bar_cur["High"] >= hi_price
                    elif bar_cur["High"] >= hi_price:
                        close_price = hi_price
                        close_trade = Trade(
                            contract=ticker,
                            price=close_price,
                            volume=position.volume,
                            side="B",
                            timestamp=date,
                            comment="Close short: SL"
                        )
                        position.reduce(close_trade)
                        self.trades_log.append(close_trade)

                        final_return = 1 - (close_price / position.avg_price)
                        if position.volume == 0:
                            position = None
                        break
                    else:
                        # floating PnL for short
                        final_return = 1 - (bar_cur["Close"] / position.avg_price)

        return final_return

    def _entry_slippage(self, intraday_df: pd.DataFrame, i: int, side="long") -> float:
        """
        i: exact time that we trade (bar index)
        Example 'slippage' model for the entry price:
          - 80% of the next bar's Open
          - 20% of the next bar's High (for long) or Low (for short)
          If there's no next bar, we fallback to the current bar's Close.
        """
        if i + 1 < len(intraday_df):
            next_bar = intraday_df.iloc[i + 1]
            if side == "long":
                return 0.8 * next_bar["Open"] + 0.2 * next_bar["High"]
            else:
                return 0.8 * next_bar["Open"] + 0.2 * next_bar["Low"]
        else:
            # fallback => bar i's close
            return intraday_df.iloc[i]["Close"]
