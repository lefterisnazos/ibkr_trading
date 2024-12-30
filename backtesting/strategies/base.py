import pandas as pd
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class BaseStrategy(ABC):
    @abstractmethod
    def prepare_data(self, app, tickers) -> Dict[str, pd.DataFrame]:
        """
        Fetch and prepare daily data. Return a dict {ticker: DataFrame}.
        """

    @abstractmethod
    def get_trade_universe_by_date(self, data: Dict[str, pd.DataFrame]) -> Dict[str, List[str]]:
        """
        Determine which tickers to trade on which dates.
        Return dict {date_str: [tickers]}.
        """

    @abstractmethod
    def generate_signals(
        self,
        intraday_data: pd.DataFrame,
        daily_row: pd.Series
    ):
        """
        Given intraday data for a single ticker & date,
        return any signals (e.g., "BUY"/"SELL"), entry price, direction, etc.
        """

    @abstractmethod
    def apply_risk_management(self, 
                              current_pnl: float, 
                              bar: pd.Series, 
                              trade_context: dict) -> Optional[float]:
        """
        (Optional) Decide whether to close a position based on stop-loss / take-profit.
        Return the PnL if we close, else None.
        """

    @abstractmethod
    def simulate_intraday(
        self,
        intraday_data: pd.DataFrame,
        daily_row: pd.Series
    ) -> float:
        """
        The main logic that uses generate_signals, apply_risk_management,
        or does any other intraday stepping to compute final PnL for that ticker & date.
        """

