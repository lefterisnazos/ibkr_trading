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
                df = df.apply(pd.to_numeric, errors="coerce")
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

        pnl, return_ = 0, 0
        for ticker, trade in self.trades.items():
            for Trade in trade:
                pnl = pnl + Trade.realized_pnl
                return_ = return_ + Trade.realized_return
        print(pnl, return_)

        with pd.ExcelWriter("my_pnl_data.xlsx", engine="openpyxl") as writer:
            for sheet_name, df in self.pnl_df.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)

        return [self.trades_df, self.pnl_df]

    def export_dict_of_dfs_to_excel(self, pnl_dict):
        # Generate a timestamped filename
        timestamp_str = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"pnl_data_{timestamp_str}.xlsx"

        if not pnl_df:
            print("No DataFrames to export!")
            return

        with pd.ExcelWriter(filename, engine="openpyxl") as writer:

            # Create a dummy sheet so there's always at least one visible sheet
            dummy_df = pd.DataFrame({"dummy": []})
            dummy_df.to_excel(writer, sheet_name="dummy", index=False)

            for sheet_name, df in self.pnl_df.items():
                # Example: convert known numeric columns
                numeric_cols = ["price", "volume", "realized_pnl", "realized_return"]
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                # Write each DataFrame to its own sheet
                df.to_excel(writer, sheet_name=sheet_name, index=False)

            # Remove the dummy sheet if we actually added any real sheets
            if len(self.pnl_df) > 0:
                del writer.book["dummy"]

            writer.save()

        print(f"DataFrames successfully exported to '{filename}'")