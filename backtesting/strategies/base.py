import pandas as pd
from typing import Dict, Optional, List
from backtesting.pos_order_trade import *
from backtesting.ib_client import IBClient
from backtesting.pos_order_trade import *

class BaseStrategy:

    def __init__(self, client_id=25):

        self.start_date = None
        self.end_date = None
        self.ib_client = IBClient(port=7497, client_id=client_id)
        self.connect_to_ib()

        self.daily_data: Dict[str, pd.DataFrame] = {}
        # final_results => {date_str: {ticker: float_pnl}}
        self.results: Dict[str, Dict[str, float]] = {}
        self.trades: Dict[str, List[Trade]]= {}               # Dict with keys: tickers, and values: List of Trade objects
        self.pnl: Dict[str, List[Trade]]= {}                  # same as self.trade{}, but we are just adding trades with a pnl (not opening trades)
        self.position: Dict[str, Position] = {}               # Dict with keys: tickers, and values: Position Objects

    def connect_to_ib(self):
        self.ib_client.connect()

    def disconnect_from_ib(self):
        self.ib_client.disconnect()

    def prepare_data(self, tickers) -> Dict[str, pd.DataFrame]:
        """
        Fetch and prepare daily data. Return a dict {ticker: DataFrame}.
        """
        raise NotImplementedError("Please implement prepare_data() in your derived strategy.")

    def run_strategy(self) -> Dict[str, Dict[str, float]]:
        """
        Orchestrates the day-by-day, ticker-by-ticker flow:
          1) get_trade_universe_by_date(daily_data)
          2) request intraday data
          3) call simulate_intraday(...)
          4) return {date: {ticker: final_pnl}}
        """
        raise NotImplementedError("Please implement run_strategy() in your derived strategy.")

    def simulate_intraday(self, ticker: str, date: str, intraday_df: pd.DataFrame) -> float:
        """
        The main logic that uses generate_signals, apply_risk_management,
        or does any other intraday stepping to compute final PnL.
        """
        raise NotImplementedError("Please implement simulate_intraday() in your derived strategy.")

    def reduce_position(self, trade: Trade, ticker: str = None):
        self.position[ticker].reduce(trade)
        if self.position[ticker].volume == 0:
            self.position[ticker] = None

        self.pnl[ticker].append(trade)
        self.trades[ticker].append(trade)
        print(trade)

    def add_position(self, trade: Trade, ticker: str = None):
        if self.position[ticker] is None:
            self.position[ticker] = Position(contract=trade.contract, price=trade.price, volume=trade.volume, side=trade.side, timestamp=trade.timestamp)
        else:
            self.position[ticker].add(trade)

        self.trades[ticker].append(trade)
        print(trade)

    def finalize_positions(self):
        """
        Closes all remaining open positions at final_date using last known price.
        """
        final_price_dict = {}
        last_date = None
        for ticker in self.daily_data:
            if not self.daily_data[ticker].empty:
                last_close = self.daily_data[ticker].iloc[-1]["Close"]
                last_date = self.daily_data[ticker].index[-1]
                final_price_dict[ticker] = last_close

        for ticker, pos in self.position.items():
            if pos is not None and pos.volume > 0:
                side_to_close = "S" if pos.side == "B" else "B"
                close_price = final_price_dict.get(ticker, pos.avg_price)
                trade = Trade(contract=ticker, price=close_price, volume=pos.volume, side=side_to_close,
                              timestamp=pos.last_update.replace(year=last_date.year, month=last_date.month, day=last_date.day, hour=16, minute=30, second=00),
                              comment="Final close at end of simulation")
                pos.reduce(trade)  # updates trade.realized_pnl
                print(trade)
                self.trades[ticker].append(trade)


