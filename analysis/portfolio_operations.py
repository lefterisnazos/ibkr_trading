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
from ib_insync import Forex, Ticker
import time


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
        self.get_positions = False
        self.portfolio_summary = {}
        self.ib.errorEvent += self.my_error_handler

        if get_positions:
            self.get_positions = True
            self.get_info_from_positions()


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

    def my_error_handler(self, reqId, errorCode, errorString, contract=None):
        """
        Custom handler that ignores specific errors (e.g. for Forex('USDEUR')).
        """
        if errorCode == 200 and 'USDEUR' in errorString:
            return
        print(f"IB Error {errorCode} (reqId {reqId}): {errorString}")

    def get_fx_rate(self, from_ccy: str, to_ccy: str, timeout: float = 1.5) -> float:
        """
        Retrieve the exchange rate from_ccy -> to_ccy using ib_insync.
        If direct pair is unavailable, tries reversed pair and inverts the rate.
        E.g., if from_ccy='USD' and to_ccy='EUR', it will first try 'USDEUR'.
        If no data, it tries 'EURUSD' and then returns 1/rate.

        :param from_ccy: e.g. 'EUR', 'USD', 'GBP', etc.
        :param to_ccy:   e.g. 'EUR', 'USD', 'GBP', etc.
        :param timeout:  seconds to wait for IB to populate snapshot data.
        :return:         exchange rate as float (if no data, returns 1.0 as fallback).
        """

        if from_ccy == to_ccy:
            return 1.0

        # A small helper to build a contract for e.g. 'EURUSD'
        def forex_contract(base, quote):
            c = Forex(base + quote)
            c.exchange = 'IDEALPRO'  # IB's main FX ECN
            return c

        # 1) Try reverse pair first, if it fails, we go to direct
        rev_contract = forex_contract(to_ccy, from_ccy)
        rev_ticker = self.ib.reqMktData(rev_contract, '', snapshot=True)

        self.ib.sleep(timeout)

        rev_rate = rev_ticker.close
        if rev_rate and rev_rate > 0.0:
            return 1.0 / rev_rate

        # 2) Try direct pair
        direct_pair = from_ccy + to_ccy
        direct_contract = forex_contract(from_ccy, to_ccy)
        direct_ticker = self.ib.reqMktData(direct_contract, '', snapshot=True)

        # Wait a bit for IB to send data
        self.ib.sleep(timeout)

        direct_rate = direct_ticker.close
        if direct_rate and direct_rate > 0.0:
            return direct_rate

        # 3) Fallback
        print(f"[WARN] Could not get an FX rate for {from_ccy}->{to_ccy} from IB. Defaulting to 1.0")
        return 1.0


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

    def get_info_from_positions(self) -> None:
        """
        Fetches the current positions from IB, calculates each position's fraction
        of the account's Net Liquidation Value, stores them in self.allocation_weights,
        and updates self.tickers with any tickers not already in the list.
        """

        # 1) Get the Net Liquidation Value
        net_liq_value = 0.0
        summary = self.ib.accountSummary(account=self.account)
        net_liq_value = float(next(val for val in summary if val.tag == 'NetLiquidation').value)
        total_cash = float(next(val for val in summary if val.tag == 'TotalCashValue').value)
        gross_position_value = float(next(val for val in summary if val.tag == 'GrossPositionValue').value)

        self.portfolio_summary = {'net_liquidation': net_liq_value,
                                'total_cash': total_cash,
                                'gross_position_value': gross_position_value}

        # Safety check to avoid dividing by zero
        if net_liq_value <= 0:
            print("Warning: NetLiquidation value is zero or unavailable. Defaulting to 1.0.")
            net_liq_value = 1.0

        # 2) Fetch positions
        portfolio = self.ib.portfolio()  # list of (account, contract, pos, avgCost)   # Prepare a dictionary for allocation weights and a set for unique tickers
        allocation_weights = {}
        tickers_set = set()

        self.currencies = {'EURUSD': None, 'EURGBP': None, 'GBPEUR': None, 'CNYEUR': None, ' EURCNY': None}
        for pos_item in portfolio:
            if pos_item.contract.secType != 'STK':
                print(f'ignored {pos_item.contract} for getting allocation weights')
                continue

            symbol = pos_item.contract.symbol
            ccy = pos_item.contract.currency  # e.g. 'USD', 'EUR'
            market_val_local = pos_item.marketValue  # in ccy

            # Convert local market value -> EUR
            fx_rate = self.get_fx_rate(ccy, 'EUR')
            market_val_eur = market_val_local * fx_rate

            weight = market_val_eur / net_liq_value
            allocation_weights[symbol] = weight
            tickers_set.add(symbol)

            print(f"[Positions] {symbol} in {ccy}, marketValue={market_val_local:.2f}, "
                  f"converted={market_val_eur:.2f} EUR, weight={weight:.4f}")

            # 3) Update self attributes
        self.allocation_weights = allocation_weights
        self.tickers = list(set(self.tickers))

    def rebalance_side(self, side_to_rebalance: str, integer_quantities=False):
        """
        Rebalance one side of the portfolio ("Longs" or "Shorts") by scaling each position.
        The scaling factor is calculated as:

           factor = (target allocation) / (current allocation)

        This factor is then applied to each position:
          new_qty = current_qty * factor,
          order difference = new_qty - current_qty.

        The function then prompts the user for the order type ("LMT" for limit or "MKT" for market).
        If a limit order is requested, the limit price is determined as follows:
          - For LONGS:
              * BUY orders (increasing exposure): limit = ask * 1.001 (i.e. 0.1% above ask)
              * SELL orders (reducing exposure): limit = bid * 0.999 (i.e. 0.1% below bid)
          - For SHORTS:
              * SELL orders (increasing short exposure): limit = bid * 0.999 (i.e. 0.1% below bid)
              * BUY orders (reducing short exposure): limit = ask * 1.001 (i.e. 0.1% above ask)
        Market orders (MKT) simply proceed without a price.
        """

        # Update portfolio allocation weights and summary.
        # self.get_info_from_positions()

        # Normalize side input and filter allocation weights.
        side_to_rebalance = side_to_rebalance.lower()
        if side_to_rebalance == "longs":
            relevant_allocs = {sym: w for sym, w in self.allocation_weights.items() if w > 0}
            prompt_msg = "Enter desired new % net liquidity for LONG positions (e.g., 30 for 30%): "
        elif side_to_rebalance == "shorts":
            relevant_allocs = {sym: w for sym, w in self.allocation_weights.items() if w < 0}
            prompt_msg = "Enter desired new % net liquidity for SHORT positions (e.g., 10 for 10%): "
        else:
            print("Invalid side specified. Please use 'Longs' or 'Shorts'.")
            return

        # Calculate current allocation for the selected side.
        if side_to_rebalance == "longs":
            current_alloc = sum(relevant_allocs.values())  # e.g., 0.50 for 50%
        else:
            # For shorts, use the absolute total of negative weights.
            current_alloc = sum(abs(w) for w in relevant_allocs.values())

        print(f"Current {side_to_rebalance.capitalize()} allocation: {current_alloc * 100:.2f}% of net liquidation.")

        # Get target allocation percentage from the user.
        try:
            target_pct = float(input(prompt_msg))
        except ValueError:
            print("Invalid input for target percentage.")
            return
        target_alloc = target_pct / 100.0

        # Compute the scaling factor.
        factor = target_alloc / current_alloc
        print(f"Scaling factor computed: {factor:.3f}")

        # Ask the user for the order type: Market (MKT) or Limit (LMT)
        order_type_input = input("Enter order type (MKT for Market, LMT for Limit): ").strip().upper()
        if order_type_input not in ["MKT", "LMT"]:
            print("Invalid order type specified. Defaulting to Market order.")
            order_type_input = "MKT"

        # Retrieve the current positions from IB.
        positions = self.ib.portfolio()
        for pos in positions:
            symbol = pos.contract.symbol

            # Filter positions based on the side.
            if symbol == 'SQQQ' or symbol == 'VXX':
                continue
            if side_to_rebalance == "longs" and pos.position <= 0:
                continue
            if side_to_rebalance == "shorts" and pos.position >= 0:
                continue

            current_shares = pos.position  # positive for longs; negative for shorts.
            new_qty_float = current_shares * factor
            order_diff = new_qty_float - current_shares

            # Skip if no significant adjustment is needed.
            if abs(order_diff) < 1:
                print(f"No significant adjustment for {symbol} (current shares: {current_shares}).")
                continue

            # Determine order direction based on order_diff.
            if order_diff > 0:
                order_side = "BUY"
            else:
                order_side = "SELL"
            order_qty = int(round(abs(order_diff)))

            # For limit orders, calculate a limit price; for market orders, leave as None.
            if order_type_input == "LMT":
                # Request a market data snapshot.
                ticker = self.ib.reqMktData(pos.contract, '', snapshot=True)
                self.ib.sleep(0.5)  # Wait briefly for data to come in.
                if side_to_rebalance == "longs":
                    if order_side == "BUY":
                        # Increasing longs: set b uy  o rder below 0.1% of current bid
                        current_bid = ticker.bid
                        if current_bid is None or current_bid <= 0:
                            print(f"Could not retrieve ask for {symbol}. Skipping order.")
                            continue
                        limit_price = current_bid * 0.999
                        price_info = f"ask: {current_bid:.2f}"
                    else:  # SELL
                        # Reducing longs: sell at 0.1% above current ask
                        current_ask = ticker.ask
                        if current_ask is None or current_ask <= 0:
                            print(f"Could not retrieve bid for {symbol}. Skipping order.")
                            continue
                        limit_price = current_ask * 1.001
                        price_info = f"bid: {current_ask:.2f}"
                else:  # side_to_rebalance == "shorts"
                    if order_side == "SELL":
                        # Increasing shorts: sell at 0.1% below current bid.
                        current_ask = ticker.ask
                        if current_ask is None or current_ask <= 0:
                            print(f"Could not retrieve bid for {symbol}. Skipping order.")
                            continue
                        limit_price = current_ask * 1.001
                        price_info = f"bid: {current_ask:.2f}"
                    else:  # BUY
                        # Reducing shorts: buy at 0.1% above current ask.
                        current_bid = ticker.bid
                        if current_bid is None or current_bid <= 0:
                            print(f"Could not retrieve ask for {symbol}. Skipping order.")
                            continue
                        limit_price = current_bid * 0.999
                        price_info = f"ask: {current_bid:.2f}"
                print(
                    f"Placing {order_side} (LMT) order for {order_qty} shares of {symbol} at limit price {limit_price:.2f} "
                    f"({price_info}, current shares: {current_shares}, desired new shares: {new_qty_float:.2f}).")
            else:
                # Market order; no limit price is calculated.
                limit_price = None
                print(f"Placing {order_side} (MKT) order for {order_qty} shares of {symbol} "
                      f"(current shares: {current_shares}, desired new shares: {new_qty_float:.2f}).")

            # Place the order via the inherited order-placement method.
            self.place_live_order(pos.contract, order_side, order_qty, order_type=order_type_input,
                                  limit_price=limit_price)

        print(f"Rebalancing of {side_to_rebalance.capitalize()} orders executed.")


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

    def compute_ticker_portfolio_correlation(self, weighted: bool = False) -> pd.Series:
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

    def compute_correlation_against_benchmarks(self, weighted: bool = False) -> pd.DataFrame:
        """
        Computes the correlation of each individual ticker (from self.tickers) against each benchmark
        (from self.ref_tickers), and then also computes the correlation of the overall portfolio/tickers
        with each benchmark. The portfolio return is computed as a weighted average (using self.allocation_weights
        if weighted=True) or a simple average otherwise.

        The returned DataFrame has tickers (and an extra row labeled 'Portfolio') as its index, and benchmarks as its columns.

        Args:
            weighted parameter is relevant only for 'Portfolio'.
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
period_start = dt.datetime(2025, 2, 1)
period_end = dt.datetime(2025, 3, 27)
anal = IBStockAnalyzer(tickers,reference, '1 day', client_id=26, get_positions=True)

#betas = anal.analyze_betas(period_start=period_start, period_end=period_end)
#corr = anal.analyze_correlations(period_start=period_start, period_end=period_end)
#port_corr = anal.compute_ticker_portfolio_correlation(weighted=True)
#bench_corr = anal.compute_correlation_against_benchmarks(weighted=True)
anal.rebalance_side('longs')
x=2
