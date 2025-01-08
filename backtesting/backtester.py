# backtester.py
import time
import pandas as pd
from typing import Dict, List
from pos_order_trade import *
import datetime as dt
from backtesting.benchmarks import *


class Backtester:
    def __init__(self, strategy, tickers):
        self.strategy = strategy
        self.tickers = tickers

        # We'll store the daily_data fetched by the strategy
        self.daily_data = None

        # final_results => {date: {ticker: float_pnl}}
        self.pnl = {}
        self.trades = {}

        # For logging all trades in a single DataFrame
        self.trades_df = pd.DataFrame()
        self.pnl_df = pd.DataFrame()

    def run(self):
        # 1) Let the strategy prepare daily data
        self.daily_data = self.strategy.prepare_data(self.tickers)

        # 2) Run the strategy
        self.trades, self.pnl = self.strategy.run_strategy()

        return

    @staticmethod
    def trades_to_dataframe(trades:  Dict[str, List[Trade]]):
        """
        Convert a list of Trade objects into a Pandas DataFrame,
        using 'timestamp' as the index.
        """
        trades_dfs = {}

        for ticker, trades_list in trades.items():
            rows = []
            for trade in trades_list:
                rows.append({"timestamp": pd.to_datetime(trade.timestamp),
                    "contract": trade.contract, "side": trade.side, "volume": trade.volume, "price": trade.price,
                    "realized_pnl": trade.realized_pnl,
                    "realized_return": trade.realized_return,
                    "comment": trade.comment})
            if rows:
                df = pd.DataFrame(rows)
                df.set_index("timestamp", inplace=True)
                df.index = pd.DatetimeIndex(df.index)
                df = (df.round(4))
                trades_dfs[ticker] = df
            else:
                trades_dfs[ticker] = pd.DataFrame()

        return trades_dfs

    def evaluate(self):
        """
        Evaluate using the provided benchmark classes.
        """
        # The strategy might store trades in self.strategy.trades
        self.trades_df = self.trades_to_dataframe(self.trades)
        self.pnl_df = self.trades_to_dataframe(self.pnl)

        return [self.trades_df, self.pnl_df]