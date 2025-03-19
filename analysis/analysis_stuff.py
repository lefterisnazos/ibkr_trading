import pickle
import os
from live.ib_client_live import IBClientLive
import time
import datetime as dt
import numpy as np
import pandas as pd
import math
from typing import Dict, List, Optional
from tqdm import tqdm
from ib_insync import Index
import matplotlib.pyplot as plt
from ib_insync import IB, Stock, util

class IBStockAnalyzer(IBClientLive):
    """
    Extends IBClientLive with analysis functions.

    Attributes:
        tickers (List[str]): List of ticker symbols to analyze.
        ref_tickers (List[str]): List of reference tickers used for beta calculations.
        bar_size (str): The data frequency (e.g., '5 mins', '1 day').
        data (Dict[str, pd.DataFrame]): Cache for fetched intraday data.
    """

    def __init__(self, tickers: List[str], ref_tickers: List[str], bar_size: str,
                 account='DU8057891', host='127.0.0.1', port=7497, client_id=999,
                 get_positions: bool = False, pickle_up: bool = False, pickle_filename: str = 'data.pkl'):
        super().__init__(account=account, host=host, port=port, client_id=client_id)
        self.tickers = tickers
        self.ref_tickers = ref_tickers
        self.bar_size = bar_size
        self.data: Dict[str, pd.DataFrame] = {}  # Cache for intraday data
        self.connect()
        self.allocation_weights = None

        if get_positions:
            self.get_tickers_from_positions()

        # If pickle_up is True, try to load cached data
        self.pickle_filename = pickle_filename
        if pickle_up:
            self.load_data(self.pickle_filename)

    def save_data(self, filename: str = None) -> None:
        """
        Pickles and saves self.data to disk so that it can be loaded in subsequent sessions.
        """
        if filename is None:
            filename = self.pickle_filename
        try:
            with open(filename, 'wb') as f:
                pickle.dump(self.data, f)
            print(f"Data successfully saved to {filename}.")
        except Exception as e:
            print(f"Error saving data to {filename}: {e}")

    def load_data(self, filename: str = None) -> None:
        """
        Loads self.data from a pickle file on disk. If the file is not found, self.data remains empty.
        """
        if filename is None:
            filename = self.pickle_filename
        if os.path.exists(filename):
            try:
                with open(filename, 'rb') as f:
                    self.data = pickle.load(f)
                print(f"Data successfully loaded from {filename}.")
            except Exception as e:
                print(f"Error loading data from {filename}: {e}")
                self.data = {}
        else:
            print(f"No pickle file found at {filename}. Starting with empty data.")
            self.data = {}


    def fetch_intraday_in_chunks(self, ticker: str, start: pd.Timestamp,
                                 end: pd.Timestamp, bar_size: str = None,
                                 chunk_size_request: int = 60) -> pd.DataFrame:
        """
        Fetch intraday data for 'ticker' from 'start' to 'end' in chunks.
        """
        if bar_size is None:
            bar_size = self.bar_size

        chunks = []
        current_end = end
        delta_days = (end - start).days
        estimated_chunks = math.ceil(delta_days / chunk_size_request) if delta_days > 0 else 1
        pbar = tqdm(total=estimated_chunks, desc=f"Intraday for {ticker}", unit="chunk", leave=True)

        while current_end > start:
            current_start = current_end - pd.Timedelta(days=chunk_size_request)
            if current_start < start:
                current_start = start

            df_chunk = self.fetch_historical_data(
                symbol=ticker,
                start_date=current_start,
                end_date=current_end,
                bar_size=bar_size,
                what_to_show='TRADES',
                use_rth=True
            )
            chunks.append(df_chunk)

            if not df_chunk.empty:
                earliest_in_chunk = df_chunk.index.min().tz_localize(None)
            else:
                break

            if earliest_in_chunk >= current_end:
                break

            current_end = earliest_in_chunk - pd.Timedelta(minutes=5)
            pbar.update(1)
            if current_start == start:
                break

        pbar.close()
        all_intraday = pd.concat(chunks, axis=0)
        all_intraday.sort_index(inplace=True)
        all_intraday = all_intraday[~all_intraday.index.duplicated(keep='first')]

        if not all_intraday.empty:
            tz_key = all_intraday.index.tz
            if tz_key is not None:
                start_local = start.tz_localize(tz_key)
                end_local = end.tz_localize(tz_key)
            else:
                start_local = start
                end_local = end
            return all_intraday.loc[(all_intraday.index >= start_local) &
                                    (all_intraday.index <= end_local)]
        else:
            return pd.DataFrame()

    def get_data(self, period_start: dt.datetime, period_end: dt.datetime,
                 frequency: str = None, chunk_size_request: int = 30) -> None:
        """
        Fetches and stores intraday data for both self.tickers and self.ref_tickers
        into self.data using fetch_intraday_in_chunks.

        Args:
            period_start (dt.datetime): Start time for data fetching.
            period_end (dt.datetime): End time for data fetching.
            frequency (str): Bar size for data; defaults to self.bar_size.
            chunk_size_request (int): Number of days per chunk.
        """
        if frequency is None:
            frequency = self.bar_size

        start_ts = pd.Timestamp(period_start)
        end_ts = pd.Timestamp(period_end)

        # Fetch data for all tickers and reference tickers.

        all_tickers = list(set(self.tickers + self.ref_tickers))
        for ticker in all_tickers:
            data = self.fetch_intraday_in_chunks(
                ticker=ticker,
                start=start_ts,
                end=end_ts,
                bar_size=frequency,
                chunk_size_request=chunk_size_request
            )
            self.data[ticker] = data

        return

    def get_tickers_from_positions(self) -> None:
        """
            Fetches the current positions from IB, calculates allocation weights based on
            the market value (absolute position size multiplied by average cost) of each position,
            normalizes these weights so they sum to 1, stores them in self.allocations, and updates
            self.tickers with any tickers found that are not already in the list.
            """
        positions = self.ib.positions()  # returns list of (account, contract, pos, avgCost)
        allocations = {}
        total_value = 0.0

        for account, contract, pos, avgCost in positions:
            symbol = contract.symbol
            # Compute market value; use abs(pos) to handle shorts
            value = abs(pos) * avgCost
            total_value += value
            allocations[symbol] = value
            print(f"[get_tickers_from_positions] {symbol}: pos={pos}, avgCost={avgCost}, value={value}")

        # Normalize allocation weights (if total_value is > 0)
        if total_value > 0:
            for symbol in allocations:
                allocations[symbol] /= total_value
        else:
            for symbol in allocations:
                allocations[symbol] = 0.0

        # Store the normalized weights in self.allocations.
        self.allocation_weights = allocations

        # Update self.tickers with any tickers from positions not already in the list.
        for symbol in allocations.keys():
            if symbol not in self.tickers:
                self.tickers.append(symbol)

        self.tickers = list((set(self.tickers)))


    def analyze_betas(self, period_start: dt.datetime, period_end: dt.datetime,
                      frequency: str = None) -> pd.DataFrame:
        """
        Calculates beta for each ticker in self.tickers relative to each reference ticker in self.ref_tickers
        using the intraday data stored in self.data.
        Args:
            period_start (dt.datetime): Start time for analysis.
            period_end (dt.datetime): End time for analysis.
            frequency (str): Bar size for data; defaults to self.bar_size.
        Returns:
            pd.DataFrame: DataFrame of beta values.
        """
        if frequency is None:
            frequency = self.bar_size

        # Ensure data is available in self.data. If not, fetch it.
        if not self.data:
            self.get_data(period_start, period_end, frequency)

        beta_matrix = {}
        for ticker in self.tickers:
            beta_matrix[ticker] = {}
            ticker_data = self.data.get(ticker, pd.DataFrame())
            if ticker_data.empty:
                for ref in self.ref_tickers:
                    beta_matrix[ticker][ref] = None
                continue

            ticker_returns = ticker_data['Close'].pct_change().dropna()
            for ref in self.ref_tickers:
                ref_data = self.data.get(ref, pd.DataFrame())
                if ref_data.empty:
                    beta_matrix[ticker][ref] = None
                    continue

                ref_returns = ref_data['Close'].pct_change().dropna()
                combined = pd.DataFrame({
                    'ticker': ticker_returns,
                    'ref': ref_returns
                }).dropna()

                if combined.empty:
                    beta_matrix[ticker][ref] = None
                else:
                    cov = combined['ticker'].cov(combined['ref'])
                    var = combined['ref'].var()
                    beta_matrix[ticker][ref] = cov / var if var != 0 else None

        beta_df = pd.DataFrame(beta_matrix).T
        return beta_df

    def analyze_correlations(self, period_start: dt.datetime, period_end: dt.datetime, frequency: str = None) -> pd.DataFrame:
        """
        Computes the correlation matrix (of returns) for all symbols in
        self.tickers + self.ref_tickers, based on intraday data stored in self.data.

        1. If self.data is empty, we call self.get_data(...) to fetch data
           for all symbols (both tickers and ref_tickers).
        2. We then compute percentage returns for each symbol.
        3. Finally, we construct a DataFrame of returns and compute the correlation matrix.

        Args:
            period_start (dt.datetime): Start time for analysis.
            period_end   (dt.datetime): End time for analysis.
            frequency (str): Bar size for data; defaults to self.bar_size.
        Returns:
            pd.DataFrame: Correlation matrix (NxN) with rows/columns = all symbols.
        """
        if frequency is None:
            frequency = self.bar_size

        all_symbols = list(set(self.tickers + self.ref_tickers))

        if not self.data:
            self.get_data(period_start, period_end, frequency)

        # Build a dict of returns for each symbol
        returns_dict = {}
        for symbol in all_symbols:
            symbol_data = self.data.get(symbol, pd.DataFrame())
            if symbol_data.empty:
                continue

            # Compute returns and drop NaNs
            symbol_returns = symbol_data['Close'].pct_change().dropna()
            returns_dict[symbol] = symbol_returns

        if not returns_dict:
            return pd.DataFrame()

        returns_df = pd.DataFrame(returns_dict)

        corr_matrix = returns_df.corr()
        corr_matrix = np.round(corr_matrix, decimals=2)

        return corr_matrix

    def compute_ticker_portfolio_correlation(self, weighted: bool = True) -> pd.Series:
        """
        For each ticker in self.tickers, compute the correlation between its returns and the returns
        of the portfolio formed by all the other tickers in self.tickers.

        If weighted is True, the portfolio returns are computed using the allocation weights stored in
        self.allocation_weights (if available); otherwise, equal weights are used.

        Returns:
            pd.Series: A series where the index is ticker and the value is the correlation (float).
        """
        correlations = {}

        # Loop over each ticker in the portfolio
        for ticker in self.tickers:
            # Define "other tickers" (exclude the ticker under consideration)
            other_tickers = [t for t in self.tickers if t != ticker]

            # Get returns series for the ticker
            try:
                ts = self.data[ticker]['Close'].pct_change().dropna()
            except KeyError:
                print(f"Data for {ticker} is missing.")
                correlations[ticker] = np.nan
                continue

            # Build a DataFrame with returns for all other tickers
            other_returns = {}
            for ot in other_tickers:
                if ot in self.data:
                    r = self.data[ot]['Close'].pct_change().dropna()
                    other_returns[ot] = r
                else:
                    print(f"Data for {ot} is missing.")

            if not other_returns:
                correlations[ticker] = np.nan
                continue

            # Align the returns series by taking the intersection of their indices
            df_other = pd.concat(other_returns, axis=1, join='inner')
            if df_other.empty:
                correlations[ticker] = np.nan
                continue

            # Compute portfolio returns as a weighted sum or simple average of the other tickers
            if weighted:
                # Use self.allocation_weights if available; otherwise, default to equal weighting
                if self.allocation_weights:
                    alloc = {ot: self.allocation_weights.get(ot, 1.0) for ot in df_other.columns}
                else:
                    alloc = {ot: 1.0 for ot in df_other.columns}

                total = sum(alloc.values())
                for ot in alloc:
                    alloc[ot] /= total
                port_return = df_other.mul(pd.Series(alloc)).sum(axis=1)
            else:
                port_return = df_other.mean(axis=1)

            # Align the ticker returns with the portfolio returns
            common_index = ts.index.intersection(port_return.index)
            if common_index.empty:
                correlations[ticker] = np.nan
            else:
                corr = ts.loc[common_index].corr(port_return.loc[common_index])
                correlations[ticker] = corr

        return pd.Series(correlations)

    def compute_portfolio_benchmark_correlation(self, weighted: bool = False) -> pd.DataFrame:
        """
        Computes the correlation of each individual ticker (from self.tickers) against each benchmark
        (from self.ref_tickers), and then also computes the correlation of the overall portfolio
        with each benchmark. The portfolio return is computed as a weighted average (using self.allocation_weights
        if weighted=True) or a simple average otherwise.

        The returned DataFrame has tickers (and an extra row labeled 'Portfolio') as its index, and benchmarks as its columns.

        Args:
            weighted (bool): If True, use self.allocation_weights (if available) to compute weighted portfolio returns.
                             If False, compute returns with equal weighting.

        Returns:
            pd.DataFrame: A DataFrame where rows are each ticker (plus 'Portfolio') and columns are benchmarks,
                          with each cell showing the correlation of returns.
        """
        import numpy as np
        correlations = {}

        # First, compute correlation for each individual ticker against each benchmark.
        for ticker in self.tickers:
            ticker_corr = {}
            if ticker not in self.data or self.data[ticker].empty:
                for bench in self.ref_tickers:
                    ticker_corr[bench] = np.nan
                correlations[ticker] = ticker_corr
                continue

            ticker_returns = self.data[ticker]['Close'].pct_change().dropna()
            for bench in self.ref_tickers:
                if bench not in self.data or self.data[bench].empty:
                    ticker_corr[bench] = np.nan
                else:
                    bench_returns = self.data[bench]['Close'].pct_change().dropna()
                    common_index = ticker_returns.index.intersection(bench_returns.index)
                    if common_index.empty:
                        ticker_corr[bench] = np.nan
                    else:
                        ticker_corr[bench] = ticker_returns.loc[common_index].corr(bench_returns.loc[common_index])
            correlations[ticker] = ticker_corr

        # Next, compute the overall portfolio return.
        port_returns_dict = {}
        for ticker in self.tickers:
            if ticker in self.data and not self.data[ticker].empty:
                r = self.data[ticker]['Close'].pct_change().dropna()
                port_returns_dict[ticker] = r
            else:
                print(f"Data for portfolio ticker {ticker} is missing.")

        if port_returns_dict:
            df_port = pd.concat(port_returns_dict, axis=1, join='inner')
            if df_port.empty:
                portfolio_return = pd.Series(dtype=float)
            else:
                if weighted:
                    if self.allocation_weights:
                        # Use allocation weights from self.allocation_weights for tickers in df_port.
                        alloc = {ticker: self.allocation_weights.get(ticker, 1.0) for ticker in df_port.columns}
                    else:
                        alloc = {ticker: 1.0 for ticker in df_port.columns}
                    total = sum(alloc.values())
                    for ticker in alloc:
                        alloc[ticker] /= total
                    portfolio_return = df_port.mul(pd.Series(alloc)).sum(axis=1)
                else:
                    portfolio_return = df_port.mean(axis=1)
        else:
            portfolio_return = pd.Series(dtype=float)

        # Compute correlations for the overall portfolio.
        portfolio_corr = {}

        for bench in self.ref_tickers:
            if bench not in self.data or self.data[bench].empty:
                portfolio_corr[bench] = np.nan
            else:
                bench_returns = self.data[bench]['Close'].pct_change().dropna()
                common_index = portfolio_return.index.intersection(bench_returns.index)
                if common_index.empty:
                    portfolio_corr[bench] = np.nan
                else:
                    portfolio_corr[bench] = portfolio_return.loc[common_index].corr(bench_returns.loc[common_index])
        correlations['Portfolio'] = portfolio_corr

        # Convert the correlations dictionary to a DataFrame.
        corr_df = pd.DataFrame(correlations).T
        corr_df = corr_df.reindex(sorted(corr_df.index, key=lambda x: (x != 'Portfolio', x)))
        return corr_df


tickers = ['QQQ','TSLA', 'SBUX', 'NBIS']
reference = ['QQQ','SPY']
period_start = dt.datetime(2025, 1, 1)
period_end = dt.datetime(2025, 3, 18)
anal = IBStockAnalyzer(tickers,reference, '1 hour', client_id=26, get_positions=True )

betas = anal.analyze_betas(period_start=period_start, period_end=period_end)
corr = anal.analyze_correlations(period_start=period_start, period_end=period_end)
port_corr = anal.compute_ticker_portfolio_correlation(weighted=True)
bench_corr = anal.compute_portfolio_benchmark_correlation(weighted=True)
x=2
