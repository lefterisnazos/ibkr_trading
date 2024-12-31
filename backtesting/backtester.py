# backtester.py
import time
import pandas as pd
from typing import Dict, List
import datetime as dt

# We'll import your metric classes here
from benchmarks.benchmarks import (
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

        # We'll store the daily_data fetched by the strategy
        self.daily_data = None

        # final_results => {date: {ticker: float_pnl}}
        self.final_results = {}

        # For logging all trades in a single DataFrame
        self.trades_df = pd.DataFrame()

    def run(self):
        # 1) Let the strategy prepare daily data
        #    Returns {ticker: DataFrame} containing Gap/AvVol
        self.daily_data = self.strategy.prepare_data(self.app, self.tickers)

        # 2) Run the strategy, passing daily_data so the strategy can
        #    look up Gap, AvVol, etc. while simulating intraday
        self.final_results = self.strategy.run_strategy(self.app, self.daily_data)

        # 3) Convert trades to a DataFrame for further analysis
        self.trades_df = self._convert_trades_to_df(self.strategy.trades_log)

    def _convert_trades_to_df(self, trades_list):
        """
        Convert the list of Trade objects to a pandas DataFrame.
        """
        rows = []
        for tr in trades_list:
            rows.append({
                "timestamp":   tr.timestamp,
                "contract":    tr.contract,
                "side":        tr.side,
                "price":       tr.price,
                "volume":      tr.volume,
                "realizedPnL": tr.realized_pnl,
                "comment":     tr.comment
            })
        return pd.DataFrame(rows)

    def evaluate(self):
        """
        Evaluate the results using your custom metrics.
        """
        # Use self.final_results => {date: {ticker: return_float}}
        absolute_ret = AbsoluteReturnEvaluation().compute(self.final_results)
        win_rate = WinRateEvaluation().compute(self.final_results)
        mean_win = MeanReturnWinner().compute(self.final_results)
        mean_loss = MeanReturnLoser().compute(self.final_results)

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
