# backtester.py
import time
import pandas as pd
from typing import Dict, List
import datetime as dt

from benchmarks.benchmarks import (
    AbsoluteReturnEvaluation,
    WinRateEvaluation,
    MeanReturnWinner,
    MeanReturnLoser
)

class Backtester:
    def __init__(self, strategy, tickers):
        self.trades = {}
        self.pnl= {}
        self.strategy = strategy
        self.tickers = tickers

        # We'll store the daily_data fetched by the strategy
        self.daily_data = None

        # final_results => {date: {ticker: float_pnl}}
        self.pnl = {}
        self.trades = {}
        self.final_results = {}

        # For logging all trades in a single DataFrame
        self.trades_df = pd.DataFrame()

    def run(self):
        # 1) Let the strategy prepare daily data
        self.daily_data = self.strategy.prepare_data(self.tickers)

        # 2) Run the strategy
        self.final_results, self.trades, self.pnl = self.strategy.run_strategy()

        # 3) Convert the strategy’s trade log to a DataFrame        self.trades_df = self._convert_trades_to_df(self.strategy.trades)

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

    def trades_to_dataframe(self, trades_list):
        """
        Convert a list of Trade objects into a sorted DataFrame
        with columns [timestamp, side, price, volume, realized_pnl, comment].
        """
        rows = []
        for tr in trades_list:
            rows.append({"timestamp": tr.timestamp, "side": tr.side, "price": tr.price, "volume": tr.volume, "realized_pnl": tr.realized_pnl, "comment": tr.comment})
        df = pd.DataFrame(rows)
        # Sort by timestamp for chronological order
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def evaluate(self):
        """
        Evaluate using the provided benchmark classes.
        """
        # The strategy might store trades in self.strategy.trades
        trades_dict = self.strategy.trades  # {ticker: [Trade, ...]}
        daily_data = self.strategy.daily_data
        positions_dict = self.strategy.position  # {ticker: Position or None}

        for bench in self.benchmarks:
            metrics = bench.compute(trades_dict, daily_data, positions_dict)
            print(f"** {bench.__class__.__name__} Results **")
            print(metrics)