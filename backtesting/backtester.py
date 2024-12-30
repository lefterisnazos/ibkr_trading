# backtester.py

import time
import pandas as pd
from typing import Dict, List

# We'll import your metric classes here
from benchmarks import (
    AbsoluteReturnEvaluation,
    WinRateEvaluation,
    MeanReturnWinner,
    MeanReturnLoser
)

class Backtester:
    def __init__(self, strategy, app, tickers):
        self.strategy = strategy
        self.app = app
        self.tickers = tickers
        self.data = None            # daily data from prepare_data
        self.top_gap_by_date = None # dict of {date: [tickers]}
        self.results = {}           # final PnL by date, ticker

    def run(self):
        """
        1) Prepare daily data.
        2) Determine trade universe by date.
        3) For each date/ticker, fetch intraday data + simulate intraday logic.
        4) Store results in self.results.
        """
        # 1) Prepare daily data
        self.data = self.strategy.prepare_data(self.app, self.tickers)

        # 2) Get top-gap or trade universe by date
        self.top_gap_by_date = self.strategy.get_trade_universe_by_date(self.data)

        # 3) Intraday simulation
        reqID = 1000
        for date, gap_list in self.top_gap_by_date.items():
            self.results[date] = {}
            for ticker in gap_list:
                # Request 5-min intraday data for that date
                self.app.ticker_event.clear()
                # histData(req_num, contract, endDate, duration, bar_size)
                self.app.reqHistoricalData(
                    reqId=reqID,
                    contract=self.app.usTechStk(ticker),
                    endDateTime=date + " 22:05:00 US/Eastern",
                    durationStr='1 D',
                    barSizeSetting='5 mins',
                    whatToShow='TRADES',
                    useRTH=1,
                    formatDate=1,
                    keepUpToDate=0,
                    chartOptions=[]
                )
                self.app.ticker_event.wait()

                # If skip => we encountered an IB error, skip this ticker
                if self.app.skip:
                    self.app.skip = False
                    self.results[date][ticker] = 0
                    reqID += 1
                    continue

                # small delay so data can buffer in
                time.sleep(3.0)
                intraday_data = self.app.data.get(reqID, None)

                # If we have data => simulate
                if intraday_data is not None and not intraday_data.empty:
                    intraday_data = intraday_data.reset_index(drop=True)
                    daily_row = self.data[ticker].loc[date]
                    pnl = self.strategy.simulate_intraday(intraday_data, daily_row)
                    self.results[date][ticker] = pnl
                else:
                    self.results[date][ticker] = 0

                reqID += 1

    def evaluate(self):
        """
        Evaluate the results using your custom metrics.
        """
        absolute_ret = AbsoluteReturnEvaluation().compute(self.results)
        win_rate = WinRateEvaluation().compute(self.results)
        mean_win = MeanReturnWinner().compute(self.results)
        mean_loss = MeanReturnLoser().compute(self.results)

        print("**********Strategy Performance Statistics**********")
        print(f"Total cumulative return: {round(absolute_ret, 4)}")
        print(f"Total win rate         : {round(win_rate, 2)}%")
        print(f"Mean return (winners)  : {round(mean_win, 4)}")
        print(f"Mean return (losers)   : {round(mean_loss, 4)}")

        # Optionally return a dict if you want to store or log them
        return {
            "absolute_return": absolute_ret,
            "win_rate": win_rate,
            "mean_win": mean_win,
            "mean_loss": mean_loss
        }
