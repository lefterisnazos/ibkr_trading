import time
import pandas as pd
from copy import deepcopy
from backtesting.backtester_app import *
from backtesting.strategies.base import *
from typing import Dict, List, Optional

# We'll assume these come from your existing modules
# from backtester_app import ticker_event, histData, dataDataframe, usTechStk
# from your_module import BaseStrategy  # whichever path holds the BaseStrategy

class OpenRangeBreakout(BaseStrategy):
    def prepare_data(self, app, tickers) -> Dict[str, pd.DataFrame]:
        """
        1) For each ticker, request 1 month of daily bars from IBKR.
        2) Convert that raw data into a dictionary of DataFrames.
        3) Compute columns: 'Gap' and 'AvVol' (5-day rolling average volume).
        4) Return data {ticker: DataFrame}.
        """

        # 1) Request daily data for each ticker
        for ticker in tickers:
            try:
                app.ticker_event.clear()
                # histData(req_num, contract, endDate, duration, candle_size)
                histData(
                    tickers.index(ticker),
                    usTechStk(ticker),
                    '',         # endDateTime
                    '1 M',      # durationStr
                    '1 day',    # barSizeSetting
                )
                app.ticker_event.wait()

            except Exception as e:
                print(e)
                print(f"Unable to extract data for {ticker}")

        # 2) Convert the collected data to DataFrame
        historicalData = dataDataframe(tickers, app)
        data = deepcopy(historicalData)

        # 3) Compute gap and average volume columns
        for hd in data:
            data[hd]["Gap"] = ((data[hd]["Open"] / data[hd]["Close"].shift(1)) - 1) * 100
            data[hd]["AvVol"] = data[hd]["Volume"].rolling(5).mean().shift(1)
            data[hd].dropna(inplace=True)

        return data

    def get_trade_universe_by_date(self, data: Dict[str, pd.DataFrame]) -> Dict[str, List[str]]:
        """
        For each date, pick the top 5 tickers by Gap.
        Return dict => {date_str: [tickers]}.
        """
        top_gap_tickers_by_date = {}
        # Assume all tickers share the same date index => we'll use the first ticker's index
        dates = data[list(data.keys())[0]].index.to_list()

        for date in dates:
            gap_series = pd.Series()
            for ticker in data:
                # Each ticker's DF has an entry for 'date'
                gap_series.loc[ticker] = data[ticker].loc[date, "Gap"]
            # Sort descending by Gap, pick top 5
            top_gap_tickers_by_date[date] = gap_series.sort_values(ascending=False)[:5].index.to_list()

            print(f"Top 5 gap stocks on {date}")
            print(gap_series.sort_values(ascending=False)[:5])

        return top_gap_tickers_by_date

    def generate_signals(self, intraday_data: pd.DataFrame, daily_row: pd.Series):
        """
        Minimal example that decides if/when to open a position:
          - If volume > 2 * daily_row["AvVol"] / 78 and price > previous hi/lo
        Return a dictionary or custom object with 'direction' and 'entry_price'.
        """
        # The first bar is your 'open range' bar
        hi_price = intraday_data.iloc[0]['High']
        lo_price = intraday_data.iloc[0]['Low']

        signals = []
        open_price = None
        direction = None

        for i in range(1, len(intraday_data)):
            bar_prev = intraday_data.iloc[i - 1]
            bar_cur = intraday_data.iloc[i]

            if bar_prev["Volume"] > 2 * daily_row["AvVol"] / 78 and open_price is None:
                # Long breakout
                if bar_cur["High"] > hi_price:
                    open_price = 0.8 * intraday_data.iloc[i + 1]["Open"] + \
                                 0.2 * intraday_data.iloc[i + 1]["High"]  # slippage
                    direction = "long"
                    signals.append({
                        "direction": direction,
                        "entry_price": open_price
                    })
                    break  # For simplicity, we stop after we get the first valid entry.

                # Short breakout
                elif bar_cur["Low"] < lo_price:
                    open_price = 0.8 * intraday_data.iloc[i + 1]["Open"] + \
                                 0.2 * intraday_data.iloc[i + 1]["Low"]
                    direction = "short"
                    signals.append({
                        "direction": direction,
                        "entry_price": open_price
                    })
                    break

        return signals

    def apply_risk_management(self,
                              current_pnl: float,
                              bar: pd.Series,
                              trade_context: dict) -> Optional[float]:
        """
        Example check for a 5% take-profit or 100% of the 'open range' as stop-loss.
        We'll assume `trade_context` includes 'direction', 'open_price', 'hi_price', 'lo_price'.
        Return the final PnL if position is closed, else None.
        """
        direction = trade_context.get("direction", None)
        open_price = trade_context.get("open_price", None)
        hi_price = trade_context.get("hi_price", None)
        lo_price = trade_context.get("lo_price", None)

        # In your code, 5% TP => hi_price * 1.05.
        # But you were also checking bar["High"] vs hi_price * 1.05, etc.

        if direction == "long":
            # If price crosses hi_price * 1.05 => close
            if bar["High"] > hi_price * 1.05:
                final_pnl = ((hi_price * 1.05) / open_price) - 1
                return final_pnl

            # If price crosses lo_price => close (stop-loss)
            elif bar["Low"] < lo_price:
                final_pnl = (lo_price / open_price) - 1
                return final_pnl

        elif direction == "short":
            # If bar["Low"] < lo_price * 0.95 => close for profit
            if bar["Low"] < lo_price * 0.95:
                final_pnl = 1 - ((lo_price * 0.95) / open_price)
                return final_pnl

            # If bar["High"] > hi_price => close for loss
            elif bar["High"] > hi_price:
                final_pnl = 1 - (hi_price / open_price)
                return final_pnl

        # If not closed yet, return None
        return None

    def simulate_intraday(
        self,
        intraday_data: pd.DataFrame,
        daily_row: pd.Series
    ) -> float:
        """
        Step through each bar (after an entry) and see if TP/SL triggers.
        Return final PnL for that day/ticker.
        """
        # 1) We get signals to see if there's a breakout entry
        signals = self.generate_signals(intraday_data, daily_row)

        # No signals => no trade => PnL = 0
        if not signals:
            return 0.0

        entry_signal = signals[0]
        direction = entry_signal["direction"]
        open_price = entry_signal["entry_price"]

        # We'll store hi_price/lo_price from the first bar
        hi_price = intraday_data.iloc[0]['High']
        lo_price = intraday_data.iloc[0]['Low']

        # 2) We iterate bars to check for exit conditions
        trade_context = {
            "direction": direction,
            "open_price": open_price,
            "hi_price": hi_price,
            "lo_price": lo_price
        }

        final_pnl = 0.0
        for i in range(1, len(intraday_data)):
            bar = intraday_data.iloc[i]

            # if not closed => apply risk mgmt
            maybe_close = self.apply_risk_management(final_pnl, bar, trade_context)
            if maybe_close is not None:
                final_pnl = maybe_close
                return final_pnl
            else:
                # keep floating PnL
                if direction == "long":
                    final_pnl = (bar["Close"] / open_price) - 1
                else:
                    final_pnl = 1 - (bar["Close"] / open_price)

        # If we get here, we never hit TP/SL. So final PnL = last bar's floating PnL
        return final_pnl
