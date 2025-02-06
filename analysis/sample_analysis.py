#!/usr/bin/env python3
"""
Example:
  1) Connect to IB via ib_insync
  2) Fetch historical data for a set of symbols
  3) Store data in a pandas DataFrame
  4) Analyze correlation & distributions
  5) Optionally build a simple AI model for portfolio weights
"""


import pandas as pd
import numpy as np
from ib_insync import IB, Stock, util
from datetime import datetime, timedelta
from sklearn.linear_model import LinearRegression  # Example model


# You could replace with a more advanced approach, e.g. a neural network from TensorFlow/PyTorch

class IBDataAnalysis:
    def __init__(self, host='127.0.0.1', port=7497, client_id=88):
        """
        Initialize IB connection parameters. (Requires TWS or IB Gateway running)
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        self.symbols = []  # We will store the list of Stock contracts
        self.prices_df = pd.DataFrame()  # Will contain historical data

    def connect_ib(self):
        """
        Establish a connection to Interactive Brokers using ib_insync.
        """
        self.ib.connect(self.host, self.port, clientId=self.client_id)
        print(f"Connected to IB on {self.host}:{self.port}, clientId={self.client_id}")

    def add_symbol(self, symbol, exchange='SMART', currency='USD'):
        """
        Create and store a Stock contract for the given symbol.
        """
        stock = Stock(symbol, exchange, currency)
        self.symbols.append(stock)

    def fetch_historical_data(self, lookback_days=365, bar_size='1 hour'):
        """
        Fetch daily historical data for each symbol in self.symbols.

        :param lookback_days: How many days of data to fetch
        :param bar_size: Bar size e.g. '1 day', '1 hour', '15 mins', etc.
        """
        if not self.symbols:
            raise ValueError("No symbols have been added. Call add_symbol() first.")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)
        all_data = {}

        for stock in self.symbols:
            # Request historical data
            bars = self.ib.reqHistoricalData(
                contract=stock,
                endDateTime=end_date,
                durationStr=f'{lookback_days} D',
                barSizeSetting=bar_size,
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1
            )

            # Convert to pandas DataFrame
            df = util.df(bars)
            if not df.empty:
                df.set_index('date', inplace=True)
                # Use 'close' as a primary column
                all_data[stock.symbol] = df['close']
            else:
                print(f"No data returned for {stock.symbol}")

        # Merge all price series into one DataFrame
        if all_data:
            self.prices_df = pd.concat(all_data, axis=1)
            self.prices_df.columns = [col for col in all_data]  # Rename columns to symbols
            print("Historical data successfully fetched and stored in prices_df.")
        else:
            print("No data fetched; self.prices_df is empty.")

    def analyze_data(self):
        """
        Perform correlation analysis and distribution checks on self.prices_df.
        """
        if self.prices_df.empty:
            print("No data to analyze. Make sure fetch_historical_data() has run.")
            return

        print("==== Correlation Matrix ====")
        corr_matrix = self.prices_df.corr()
        print(corr_matrix)

        print("==== Basic Statistics ====")
        print(self.prices_df.describe())

        # Example distribution analysis: each symbol’s histogram
        # You can tailor or expand this in many ways.
        print("Generating distribution stats (you could also visualize histograms).")
        for symbol in self.prices_df.columns:
            sym_data = self.prices_df[symbol].dropna()
            mean_val = sym_data.mean()
            std_val = sym_data.std()
            print(f"{symbol} -> Mean: {mean_val:.2f}, StdDev: {std_val:.2f}")

    def build_ai_model_for_weights(self):
        """
        A *very* simplistic example of an ML-based approach to weighting.
        (This is just for demonstration and won't be a fully valid portfolio model.)

        We'll:
          1) Assume the next day's price is the 'target'
          2) Attempt a simple regression on the previous day's prices
          3) Then interpret coefficients as 'weights'
        """

        if self.prices_df.empty:
            print("No data for model building. Make sure fetch_historical_data() has run.")
            return

        # Prepare data for a dummy regression example
        df = self.prices_df.copy().dropna()
        # Shift the entire DataFrame forward by 1 day to serve as "target" (e.g. next-day price)
        df_target = df.shift(-1).dropna()
        df = df.iloc[:-1, :]  # align with target’s shape

        # For demonstration, let's target one symbol's next-day price
        # or an average of all next-day prices
        # Here, we’ll just pick the first symbol in the columns as an example.
        target_symbol = df.columns[0]
        X = df.values  # features: all symbols
        y = df_target[target_symbol].values  # target: next-day price of the first symbol

        # Train a simple linear regression
        model = LinearRegression()
        model.fit(X, y)

        # Extract coefficients (these could be interpreted as “weights”)
        weights = model.coef_

        # Print out the results
        print("=== AI Model for Weights (Very Basic LinearRegression) ===")
        print(f"Target symbol: {target_symbol}")
        print("Features (Symbols):", list(df.columns))
        print("Learned Coefficients (Weights):", weights)

        # Here you might do further transformation, e.g. forcing sum(weights)=1, etc.
        # This is just a demonstration.

    def disconnect_ib(self):
        """
        Disconnect from Interactive Brokers.
        """
        self.ib.disconnect()
        print("Disconnected from IB")


if __name__ == '__main__':
    # Example usage:
    analysis = IBDataAnalysis()
    analysis.connect_ib()

    # Add a few symbols (could be stocks, ETFs, etc.)
    analysis.add_symbol("SPY")
    analysis.add_symbol("TSLA")
    analysis.add_symbol("IBKR")
    analysis.add_symbol("QQQ")

    # Fetch 1 year (365 days) of daily data
    analysis.fetch_historical_data(lookback_days=365, bar_size='1 hour')

    # Perform correlation & distribution analysis
    analysis.analyze_data()

    # Build a (very) simplified AI model for weighting
    analysis.build_ai_model_for_weights()

    # Clean up
    analysis.disconnect_ib()