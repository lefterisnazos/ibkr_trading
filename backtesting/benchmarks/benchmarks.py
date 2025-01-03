from abc import ABC, abstractmethod

class Benchmark(ABC):
    """
    Base class for all benchmarks/statistics.
    Each derived class should only read data; no trade creation or modification.
    """

    @abstractmethod
    def compute(self, trades_dict, daily_data):
        """
        :param trades_dict: {ticker: [Trade(...), Trade(...), ...]}
        :param daily_data: {ticker: pd.DataFrame with daily or intraday data}
        :return: a statistics dictionary/DataFrame
        """
        pass


import pandas as pd

class DailyPnLBenchmark(Benchmark):
    """
    Reads trades (realized PnL) and daily close data to produce
    a day-by-day PnL time series for each ticker, plus portfolio total.
    """

    def compute(self, trades_dict, daily_data):
        """
        Return a DataFrame with columns = [tickers..., 'portfolio'],
        index = daily dates, values = daily PnL (realized + floating).
        """

        # Build an empty DataFrame of all unique dates across all tickers
        all_dates = set()
        for tkr, df in daily_data.items():
            all_dates.update(df.index)
        all_dates = sorted(list(all_dates))

        df_pnl = pd.DataFrame(index=all_dates)

        # For each ticker, compute daily PnL
        for ticker, trades_list in trades_dict.items():
            # 1) Convert trades to a DataFrame
            df_trades = self._trades_to_dataframe(trades_list)

            # 2) Reconstruct daily realized/floating (or only realized if you prefer)
            df_ticker_pnl = self._compute_daily_pnl_for_ticker(ticker, df_trades, daily_data[ticker])

            # Merge this series into df_pnl
            df_pnl[ticker] = df_ticker_pnl

        # Sum across tickers to get 'portfolio'
        df_pnl["portfolio"] = df_pnl.sum(axis=1)
        return df_pnl

    def _trades_to_dataframe(self, trades_list):
        rows = []
        for tr in trades_list:
            rows.append({
                "timestamp": tr.timestamp,
                "side": tr.side,
                "price": tr.price,
                "volume": tr.volume,
                "realized_pnl": tr.realized_pnl,
                "comment": tr.comment
            })
        df = pd.DataFrame(rows)
        # If no trades, return empty
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df.sort_values("timestamp", inplace=True)
            df.set_index("timestamp", drop=True, inplace=True)
        return df

    def _compute_daily_pnl_for_ticker(self, ticker, df_trades, df_daily):
        """
        Given:
          - df_trades: DataFrame of trades for this ticker
          - df_daily: daily price data (with 'Close' at least)
        We produce a pd.Series of daily PnL (index = daily dates).
        Here, we might consider only realized PnL from trades, or also do floating PnL.
        """

        # Create an empty Series for daily PnL
        daily_dates = df_daily.index
        series_pnl = pd.Series(0.0, index=daily_dates)

        # For realized PnL from trades, we sum trades that occur on each date
        # (assuming trade.timestamp is daily, or you floor intraday to daily)
        if not df_trades.empty:
            # group trades by date
            trades_by_date = df_trades.groupby(pd.Grouper(freq='D'))
            for date, group in trades_by_date:
                # sum realized pnl in that group
                date_pnl = group["realized_pnl"].sum()
                # place it in the series (only if date in daily_dates)
                if date in series_pnl.index:
                    series_pnl.loc[date] += date_pnl

        # If you want floating PnL for open positions, you'd do a more advanced
        # reconstruction. For brevity, let's assume we just record realized PnL.

        return series_pnl


class DailySharpeBenchmark(Benchmark):
    """
    Computes daily Sharpe ratio from the daily PnL time series.
    If you only have realized PnL, this will be a partial picture.
    """

    def __init__(self, risk_free_rate=0.0):
        self.risk_free_rate = risk_free_rate

    def compute(self, trades_dict, daily_data):
        # Reuse daily PnL
        df_pnl = DailyPnLBenchmark().compute(trades_dict, daily_data)

        # Suppose the 'portfolio' column is total daily PnL
        # If you want daily returns, you'd need to define your "capital"
        # or turn PnL into a daily return. E.g.:
        # df_pnl["portfolio_return"] = df_pnl["portfolio"] / capital

        # For demo, let's treat PnL as if it's "returns"
        daily_returns = df_pnl["portfolio"]

        sharpe = self._compute_sharpe(daily_returns)
        return {
            "daily_pnl": df_pnl,
            "sharpe_ratio": sharpe
        }

    def _compute_sharpe(self, returns_series):
        # basic daily Sharpe = mean(returns - r_f) / std(returns)
        excess = returns_series - self.risk_free_rate
        if excess.std() == 0:
            return 0.0
        return excess.mean() / excess.std()

