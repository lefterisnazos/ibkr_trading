from live.ib_client_live import IBClientLive
import time
import datetime as dt
import pandas as pd
import math
from typing import Dict, List, Optional
from tqdm import tqdm
from ib_insync import Index
import matplotlib.pyplot as plt

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
                 account='DU8057891', host='127.0.0.1', port=7497, client_id=999):
        super().__init__(account=account, host=host, port=port, client_id=client_id)
        self.tickers = tickers
        self.ref_tickers = ref_tickers
        self.bar_size = bar_size
        self.data: Dict[str, pd.DataFrame] = {}  # Cache for intraday data
        self.connect()

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

        return corr_matrix


tickers = ['QQQ','TSLA', 'SBUX', 'NBIS', 'OKLO' , 'MSTR', 'VXX']
reference = ['QQQ','SPY',]
period_start = dt.datetime(2025, 1, 1)
period_end = dt.datetime(2025, 3, 13)
anal = IBStockAnalyzer(tickers,reference, '30 mins', client_id=26)

betas = anal.analyze_betas(period_start=period_start, period_end=period_end)
corr = anal.analyze_correlations(period_start=period_start, period_end=period_end)
x=2
