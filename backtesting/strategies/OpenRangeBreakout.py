import time
import pandas as pd

from backtesting.strategies.base import BaseStrategy

# Suppose you have these risk management classes already
from risk_management import Position, Trade

# Import your IB contract builder if needed
from backtesting.backtester_app import usTechStk

class OpenRangeBreakout(BaseStrategy):
    """
    Implements the open range breakout strategy:
      1) Prepare daily data to identify top-gap tickers
      2) For each date, request intraday data to check breakouts, 
         enter position, apply stop-loss / take-profit
    """

    def prepare_data(self, app, tickers):
        """
        Use the BacktesterApp to request daily data for each ticker, 
        and build Gap/AvVol columns.
        Returns a dict {ticker: pd.DataFrame}.
        """
        # 1) Request daily data
        for idx, ticker in enumerate(tickers):
            app.ticker_event.clear()
            app.reqHistoricalData(
                reqId=idx,
                contract=usTechStk(ticker),
                endDateTime='',
                durationStr='1 M',        # 1 month
                barSizeSetting='1 day',
                whatToShow='TRADES',
                useRTH=1,
                formatDate=1,
                keepUpToDate=0,
                chartOptions=[]
            )
            app.ticker_event.wait()

            if app.skip:
                # If there was an error, you can reset skip, or handle differently
                print(f"Skipping logic for {ticker} due to IB error.")
                app.skip = False

        # 2) Build data dictionary from app.data
        #    Each key in app.data is reqId => We'll map it to tickers
        data = {}
        for idx, ticker in enumerate(tickers):
            df = app.data.get(idx, None)

            if df is not None:
                df = df.copy().reset_index(drop=True)
                df.set_index("Date", inplace=True)

                # Calculate gap and rolling average volume
                df["Gap"] = ((df["Open"] / df["Close"].shift(1)) - 1) * 100
                df["AvVol"] = df["Volume"].rolling(5).mean().shift(1)
                df.dropna(inplace=True)
                data[ticker] = df

            else:
                print(f"No daily data found for {ticker}.")
                data[ticker] = pd.DataFrame()
        return data

    def run_strategy(self, app, data):
        """
        1) Identify top gap tickers for each date.
        2) Request intraday data (5-min bars).
        3) Implement open range breakout logic.
        4) Return date_stats => {date: {ticker: float_return}}.
        """
        # 1. Build top-gap dictionary: {date: [tickers]}
        top_gap_by_date = self._get_top_gap_by_date(data)

        # 2. For each date and ticker, request intraday data & simulate
        date_stats = {}
        reqID = 1000

        for date, gap_list in top_gap_by_date.items():
            date_stats[date] = {}

            for ticker in gap_list:
                # Request intraday data
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
                    # If error from IB => skip this ticker for that date
                    app.skip = False
                    date_stats[date][ticker] = 0
                    reqID += 1
                    continue

                time.sleep(1.0)  # Let data buffer in

                intraday_df = app.data.get(reqID, None)
                if intraday_df is None or intraday_df.empty:
                    date_stats[date][ticker] = 0
                    reqID += 1
                    continue

                intraday_df = intraday_df.reset_index(drop=True)
                date_stats[date][ticker] = self._simulate_intraday(intraday_df, data[ticker].loc[date])

                reqID += 1

        return date_stats

    def _get_top_gap_by_date(self, data):
        """
        Return dict {date: list_of_top_5_tickers_by_gap}
        """
        # We'll assume each ticker's DataFrame has the same date index
        # and that data[ticker] is a DataFrame with a 'Gap' column
        top_gap_by_date = {}
        all_dates = set()
        for tkr, df in data.items():
            all_dates.update(df.index.unique())

        # Sort the dates for a consistent loop order
        all_dates = sorted(list(all_dates))

        for d in all_dates:
            gap_dict = {}
            for tkr, df in data.items():
                if d in df.index:
                    gap_dict[tkr] = df.loc[d, "Gap"]
            # Sort by descending gap
            top_tickers = sorted(gap_dict.items(), key=lambda x: x[1], reverse=True)[:5]
            top_gap_by_date[d] = [t[0] for t in top_tickers]

        return top_gap_by_date

    def _simulate_intraday(self, intraday_df, daily_row):
        """
        The open range breakout logic for intraday bars:
          - Check for breakout above high or below low
          - If volume threshold is met, open position
          - Apply stop-loss and take-profit
          - Return final return from the trade (float)
        """
        # Pre-market high & low from the first bar
        hi_price = intraday_df.loc[0, "High"]
        lo_price = intraday_df.loc[0, "Low"]

        position = None
        open_price = None
        direction = None
        result_return = 0

        # We'll get volume threshold from daily_row["AvVol"] if present
        volume_threshold = 2 * (daily_row["AvVol"] / 78) if ("AvVol" in daily_row and not pd.isna(daily_row["AvVol"])) else 1e6

        for i in range(1, len(intraday_df)):
            bar_prev = intraday_df.iloc[i - 1]
            bar_cur = intraday_df.iloc[i]

            # Entry logic: if previous bar's volume is large, check breakouts
            if bar_prev["Volume"] > volume_threshold and position is None:
                # If current bar’s high > hi_price => long breakout
                if bar_cur["High"] > hi_price:
                    direction = "B"
                    open_price = bar_cur["Close"]
                    position = Position(contract="TICKER",  # Or ticker symbol
                                        price=open_price,
                                        volume=100,
                                        side=direction,
                                        timestamp="some_date")

                # If current bar's low < lo_price => short breakout
                elif bar_cur["Low"] < lo_price:
                    direction = "S"
                    open_price = bar_cur["Close"]
                    position = Position(contract="TICKER",
                                        price=open_price,
                                        volume=100,
                                        side=direction,
                                        timestamp="some_date")

            # If we have a position, check for SL/TP
            if position is not None:
                # For example, 5% take-profit, 2% stop-loss
                TP = 0.05
                SL = 0.02

                if position.side == "B":
                    # 1) If high >= hi_price*(1+TP), close for profit
                    if bar_cur["High"] >= hi_price * (1 + TP):
                        close_price = hi_price * (1 + TP)
                        trade = Trade(position.contract, close_price, position.volume, "S", "some_date")
                        position.reduce(trade)
                        result_return = (close_price / open_price) - 1
                        position = None
                        break

                    # 2) If low <= lo_price*(1-SL), close for loss
                    elif bar_cur["Low"] <= lo_price * (1 - SL):
                        close_price = lo_price * (1 - SL)
                        trade = Trade(position.contract, close_price, position.volume, "S", "some_date")
                        position.reduce(trade)
                        result_return = (close_price / open_price) - 1
                        position = None
                        break

                    else:
                        # floating PnL
                        result_return = (bar_cur["Close"] / open_price) - 1

                else:  # Short side
                    # 1) If low <= lo_price*(1-TP), close for profit
                    if bar_cur["Low"] <= lo_price * (1 - TP):
                        close_price = lo_price * (1 - TP)
                        trade = Trade(position.contract, close_price, position.volume, "B", "some_date")
                        position.reduce(trade)
                        result_return = 1 - (close_price / open_price)
                        position = None
                        break

                    # 2) If high >= hi_price*(1+SL), close for loss
                    elif bar_cur["High"] >= hi_price * (1 + SL):
                        close_price = hi_price * (1 + SL)
                        trade = Trade(position.contract, close_price, position.volume, "B", "some_date")
                        position.reduce(trade)
                        result_return = 1 - (close_price / open_price)
                        position = None
                        break

                    else:
                        # floating PnL for short
                        result_return = 1 - (bar_cur["Close"] / open_price)

        return result_return
