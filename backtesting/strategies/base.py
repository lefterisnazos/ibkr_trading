import pandas as pd
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class BaseStrategy:

    def __init__(self):
        self.start_date = None
        self.end_date = None


    def prepare_data(self, app, tickers) -> Dict[str, pd.DataFrame]:
        """
        Fetch and prepare daily data. Return a dict {ticker: DataFrame}.
        """
        raise NotImplementedError("Please implement prepare_data() in your derived strategy.")

    def get_trade_universe_by_date(self, data: Dict[str, pd.DataFrame]) -> Dict[str, List[str]]:
        """
        Determine which tickers to trade on which dates.
        Return dict {date_str: [tickers]}.
        """
        raise NotImplementedError("Please implement get_trade_universe_by_date() in your derived strategy.")

    def generate_signals(self, intraday_data: pd.DataFrame, daily_row: pd.Series):
        """
        Given intraday data for a single ticker & date,
        return any signals (e.g., "BUY"/"SELL"), entry price, direction, etc.
        """
        raise NotImplementedError("Please implement generate_signals() in your derived strategy.")

    def apply_risk_management(self, current_pnl: float, bar: pd.Series, trade_context: dict) -> Optional[float]:
        """
        Decide whether to close a position based on stop-loss / take-profit.
        Return the PnL if we close, else None.
        """
        raise NotImplementedError("Please implement apply_risk_management() in your derived strategy.")

    def simulate_intraday(self, ticker: str, date: str, intraday_df: pd.DataFrame, daily_row: pd.Series) -> float:
        """
        The main logic that uses generate_signals, apply_risk_management,
        or does any other intraday stepping to compute final PnL.
        """
        raise NotImplementedError("Please implement simulate_intraday() in your derived strategy.")

    def run_strategy(self, app, daily_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, float]]:
        """
        Orchestrates the day-by-day, ticker-by-ticker flow:
          1) get_trade_universe_by_date(daily_data)
          2) request intraday data
          3) call simulate_intraday(...)
          4) return {date: {ticker: final_pnl}}
        """
        raise NotImplementedError("Please implement run_strategy() in your derived strategy.")

