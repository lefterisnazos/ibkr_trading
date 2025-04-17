import time
import datetime as dt
import pandas as pd
import pytz
from ib_insync import IB, Stock, util, Fill, Trade as IBTrade, Contract
import math
from typing import Dict, List, Tuple, Optional
from tqdm import tqdm
import numpy as np

from ib_insync import MarketOrder, LimitOrder, StopOrder, Order, BracketOrder, Trade, Position

# bars = ib.reqRealTimeBars(contract, whatToShow='TRADES', useRTH=True, barSize=5)
# # bars is an ib_insync “RealTimeBarList” which updates automatically

# tickers = ib.reqMktData(contract, '', False, False)
# # Then you can read live market data from ticker.bid, ticker.ask, ticker.last, etc.

# trade = ib.placeOrder(contract, LimitOrder("BUY", quantity=100, lmtPrice=123.45))
# # trade is an ib_insync “Trade” object. trade.orderStatus, trade.fills, etc. are updated automatically.

class IBClientLive:
    """
    Merges 'IBClient' + 'BaseStrategyLive' roles into a single class that:
      - Manages the ib_insync.IB() connection
      - Tracks positions/trades/pnl
      - Receives tradeUpdate events
      - Provides methods to place orders & update positions
    """
    def __init__(self, account, host='127.0.0.1', port=7497, client_id=26):
        self.account = account
        self.host = host
        self.port = port
        self.client_id = client_id

        # Create the IB instance
        self.ib = IB()

        # Book-keeping
        self.positions: Dict[str, Dict[str, float]] = {}
        self.trades: Dict[str, List[IBTrade]] = {}
        self.open_orders: Dict[str, List[Order]] = {}


        self.all_orders: Dict[str, List[Order]] = {}
        self.all_trades: Dict[str, List[IBTrade]] = {}
        self.all_executions: Dict[str, Dict[str, object]] = {}

    def connect(self):
        """
        Connect to the IB TWS/Gateway using ib_insync.IB.
        """
        try:
            self.ib.connect(host=self.host, port=self.port, clientId=self.client_id, account=self.account)
            print("Connected to IB.")
        except Exception as e:
            print(f"Could not connect to IB: {e}")

    def disconnect(self):
        """
        Disconnect from IB.
        """
        self.ib.disconnect()
        print("Disconnected from IB.")

    def create_contract(self, symbol: str):
        """
        Attempt to find a valid contract for `symbol` by trying multiple
        exchange/currency combinations and calling `ib.qualifyContracts`.
        Returns the first matching contract, or None if none match.
        """
        # Common guesses for various exchanges
        guesses = [
            Stock(symbol, 'SMART', 'USD'),   # US listings
            Stock(symbol, 'AEB', 'EUR'),  # Euronext Amsterdam
            Stock(symbol, 'LSE', 'GBP'),  # London Stock Exchange
            Stock(symbol, 'SBF', 'EUR'),     # Euronext Paris (France)
            Stock(symbol, 'IBIS', 'EUR'),    # Xetra/Frankfurt (Germany)
            Stock(symbol, 'BVME', 'EUR'),    # Borsa Italiana (Italy) - code may vary
            Stock(symbol, 'BOVESPA', 'BRL'), # Brazil
            Stock(symbol, 'BCBA', 'ARS'),    # Argentina
            Stock(symbol, 'SEHK', 'HKD'),    # Hong Kong
            Stock(symbol, 'TSE', 'JPY'),     # Tokyo Stock Exchange
            Stock(symbol, 'ATH', 'EUR')   # Athens Stock Exchange
        ]

        for guess in guesses:
            qualified_list = self.ib.qualifyContracts(guess)
            if qualified_list:
                # If there's a unique match or we just take the first match
                return qualified_list[0]

        # If no guess matched
        return None

    def subscribe_realtime_bars(self, contract, bar_size=5, what_to_show='TRADES'):
        """
        Subscribe to real-time bars; returns an ib_insync.RealTimeBarList object that updates automatically.
        """
        return self.ib.reqRealTimeBars(contract=contract, barSize=bar_size, whatToShow=what_to_show, useRTH=True)

    def place_live_order(self, contract: Contract, side, quantity, order_type='MKT', limit_price=None, rth_only=False):
        """
        Create and place an IB order. Returns ib_insync.Trade object.
        rth_only, to place order on regular hours only.
        """

        if order_type == 'MKT':
            order = MarketOrder(side, quantity)
        elif order_type == 'LMT':
            if limit_price is None:
                raise ValueError("limit_price must be specified for a limit order.")
            order = LimitOrder(side, quantity, np.round(limit_price,2))
        # etc. for Stop, StopLimit, etc.
        if not rth_only:
            outside_rth = self.is_outside_rth(contract)
            if outside_rth :
                order.outsideRTH = True
                order.totalQuantity = math.ceil(quantity)

        contract = self.ib.qualifyContracts(contract)[0]

        try:
            trade = self.ib.placeOrder(contract, order)
        except Exception as e:
            # Check if the error suggests that fractional shares are not accepted
            if "fractional" in str(e).lower():
                print("Fractional shares not accepted. Rounding quantity up and re-trying...")
                order.totalQuantity = math.ceil(quantity)
                trade = self.ib.placeOrder(contract, order)
            else:
                raise e

        print(f"Placed {side} order for {quantity} shares of {contract.symbol} at {limit_price} (order: {order})")
        return trade

    def is_outside_rth(self, contract) -> bool:
        """
        Return True when *now* (in the contract’s local TZ) is **outside**
        IB's Regular Trading Hours (RTH).

        RTH comes from `liquidHours`.  If that field is empty we fall back to
        `tradingHours`, but remember that `tradingHours` includes the
        pre‑ and post‑market sessions as well.
        """
        import datetime as dt
        import pytz

        details = self.ib.reqContractDetails(contract)
        if not details:
            print("No contract details; assuming we're inside RTH.")
            return False

        cd = details[0]
        # Prefer the more precise RTH definition
        session_str = cd.   liquidHours or cd.tradingHours
        tz_id = cd.timeZoneId

        if not session_str or not tz_id:
            print("Missing liquidHours/tradingHours or TZ info; assuming RTH.")
            return False

        try:
            tz = pytz.timezone(tz_id)
        except Exception as e:
            print(f"Bad timezone '{tz_id}': {e}.  Assuming RTH.")
            return False

        now_local = dt.datetime.now(tz)

        # Each segment is either   YYYYMMDD:HHMM-YYYYMMDD:HHMM   or   YYYYMMDD:CLOSED
        for seg in session_str.split(';'):
            # Skip “CLOSED” days straight away
            if seg.endswith(":CLOSED"):
                continue

            try:
                open_part, close_part = seg.split('-')
                open_date, open_time = open_part.split(':', 1)
                close_date, close_time = close_part.split(':', 1)

                # Use the date from the open leg
                session_date = dt.datetime.strptime(open_date, "%Y%m%d").date()

                open_dt = tz.localize(dt.datetime.combine(session_date,
                                                          dt.time(int(open_time[:2]), int(open_time[2:]))))
                close_dt = tz.localize(dt.datetime.combine(session_date,
                                                           dt.time(int(close_time[:2]), int(close_time[2:]))))

                # Are we inside this RTH window?
                if open_dt <= now_local <= close_dt:
                    return False  # inside → NOT outside RTH

            except Exception as e:
                print(f"Could not parse session '{seg}': {e}")
                continue

        # Not in any liquidHours segment ⇒ outside RTH
        return True

    def get_orders(self, open_orders_only: bool = True) :
        """
        Retrieve either all orders or just open orders, grouping them by symbol.
        :param open_orders_only: If True, fetch openOrders(), else fetch orders().
        :return: Dictionary: { symbol -> list of Order objects }
        """
        if open_orders_only:
            orders = self.ib.openOrders()
            self.open_orders = self.group_by_symbol(orders)
        else:
            orders = self.ib.orders()
            self.all_orders = self.group_by_symbol(orders)

    def get_trades(self, open_trades_only: bool = True) :
        """
        Retrieve either all trades or just open trades, grouping them by symbol.
        :param open_trades_only: If True, fetch openTrades(), else fetch trades().
        """
        if open_trades_only:
            trades_list = self.ib.openTrades()
            self.trades = self.group_by_symbol(trades_list)
        else:
            trades_list = self.ib.trades()
            self.all_trades = self.group_by_symbol(trades_list)

    def get_executions(self):
        pass

    def get_positions(self, account, contract, pos, avgCost):

        positions = self.ib.positions()
        self.positions = {}
        for account, contract, pos, avgCost in positions:
            self.positions[contract.symbol] = {'position': pos, 'avgCost': avgCost, 'contract': contract, 'account': account}

        print(f"[on_position_update] Updated position: {contract.symbol} -> pos={pos}, avgCost={avgCost}")

    def get_all_executions(self):
        """
        Fetch all executions/fills from IB, store them in self.all_executions, and return them.
        """
        # executions() returns a dict of execId -> (contract, execution)
        ib_execs = self.ib.executions()

        self.all_executions = {}
        for exec_id, (contract, execution) in ib_execs.items():
            self.all_executions[exec_id] = {'symbol': contract.symbol,
                                            'side': execution.side,
                                            'shares': execution.shares,
                                            'price': execution.avgPrice,
                                            'time': execution.time,
                                            'orderId': execution.orderId,
                                            'execId': exec_id}
            print(f"[get_all_executions] Execution {exec_id} -> {self.all_executions[exec_id]}")

        return self.all_executions
    def on_trade_update(self, trade: IBTrade):
        """
        Called automatically whenever a trade is updated with partial fill, fill, etc.
        We convert the ib_insync fill to our local 'Trade' object,
        then call add_position() or reduce_position().
        """
        if not trade.fills:
            return

        for fill in trade.fills:
            ib_side = fill.execution.side  # "BOT" or "SLD"
            local_side = "B" if ib_side == "BOT" else "S"

            ticker = trade.contract.symbol
            fill_price = fill.execution.avgPrice
            fill_qty = fill.execution.shares
            fill_time = fill.execution.time

            # Ensure we have a dictionary entry
            if ticker not in self.trades:
                self.trades[ticker] = []
            if ticker not in self.pnl:
                self.pnl[ticker] = []

    def fetch_historical_data(self, symbol: str, start_date: dt.datetime, end_date: dt.datetime, bar_size: str, what_to_show: str = 'TRADES', use_rth: bool = True) -> pd.DataFrame:
        """
        Uses ib_insync to request historical data for `symbol` as a DataFrame.
        :param symbol: Ticker symbol (e.g., 'AAPL').
        :param start_date: Start datetime (Python `datetime`) for the historical data request.
        :param end_date: End datetime (Python `datetime`) for the historical data request.
        :param duration_str: IB-compatible duration string, e.g. "1 Y", "1 D", etc.
        :param bar_size: IB-compatible bar size, e.g. "1 day", "5 mins".
        :param what_to_show: 'TRADES', 'MIDPOINT', etc.
        :param use_rth: Whether to use regular trading hours only.
        :return: DataFrame with columns: [Date, Open, High, Low, Close, Volume, ...]
        """
        contract = self.create_contract(symbol)
        if not contract:
            print(f"Could not find a valid contract for {symbol}.")
            return pd.DataFrame()

        tz_suffix = self.get_exchange_timezone(contract.exchange)
        if tz_suffix == 'US/Eastern':
            end_date_str = end_date.strftime("%Y%m%d %H:%M:%S") + ' US/Eastern'
        else:
            end_date_str = end_date.strftime("%Y%m%d %H:%M:%S")

        duration_str = self.get_ib_duration_str(start_date, end_date)

        try:
            bars = self.ib.reqHistoricalData(
                contract=contract,
                endDateTime=end_date_str,
                durationStr=duration_str,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=use_rth,
                formatDate=1,
                keepUpToDate=False,
            )
        except Exception as e:
            print(f"Error fetching data for {symbol}: {e}")
            return pd.DataFrame()

        df = util.df(bars)
        if df is None or df.empty:
            return pd.DataFrame()

        # Rename columns to a standard format
        df.rename(
            columns={
                'date': 'Date',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            },
            inplace=True
        )
        df.set_index('Date', inplace=True)
        df.sort_index(inplace=True)
        df.index = pd.DatetimeIndex(df.index)
        return df

    def fetch_intraday_in_chunks(self, ticker: str, start: pd.Timestamp, end: pd.Timestamp, bar_size: str = "5 mins", chunk_size_request: int = 60
            # number of days per chunk
    ) -> pd.DataFrame:
        """
        Fetch intraday data for 'ticker' from 'start' to 'end' in chunks of 'chunk_size_request' days.

        :param ticker: Ticker symbol, e.g. 'AAPL'.
        :param start: Earliest datetime (pd.Timestamp).
        :param end: Latest datetime (pd.Timestamp).
        :param bar_size: e.g. '5 mins'.
        :param chunk_size_request: int, number of days in each chunk (e.g. 60 means ~2 months).
        :return: A DataFrame of intraday bars in [start, end].
        """
        chunks = []
        current_end = end

        delta_days = (end - start).days
        estimated_chunks = math.ceil(delta_days / chunk_size_request) if delta_days > 0 else 1

        pbar = tqdm(total=estimated_chunks, desc=f"Intraday for {ticker}", unit="chunk", leave=True)  # 'leave=True' means the bar stays after completion)
        while current_end > start:
            # subperiod_start is chunk_size_request days before current_end
            current_start = current_end - pd.Timedelta(days=chunk_size_request)
            # If subperiod_start < start, clamp it
            if current_start < start:
                current_start = start

            # Now fetch data from subperiod_start to current_end
            df_chunk = self.fetch_historical_data(symbol=ticker, start_date=current_start, end_date=current_end, bar_size=bar_size, what_to_show='TRADES', use_rth=True)
            chunks.append(df_chunk)

            # The earliest bar we got in this chunk
            earliest_in_chunk = df_chunk.index.min().tz_localize(None)
            # If we didn't get older data => break
            if earliest_in_chunk >= current_end:
                break

            # Move current_end to just before earliest_in_chunk
            current_end = earliest_in_chunk - pd.Timedelta(minutes=5)
            pbar.update(1)


            # If subperiod_start == start => done
            if current_start == start:
                break

        pbar.close()

            # Concatenate
        all_intraday = pd.concat(chunks, axis=0)
        all_intraday.sort_index(inplace=True)
        all_intraday = all_intraday[~all_intraday.index.duplicated(keep='first')]

        start = start.tz_localize(all_intraday.index.tz.key)  # to convert eg to Us/Eastern/ or tz_convert(...)
        end = end.tz_localize(all_intraday.index.tz.key)

        # Finally, slice strictly to [start, end]
        return all_intraday.loc[(all_intraday.index >= start) & (all_intraday.index <= end)]


    @staticmethod
    def get_ib_duration_str(start_date: dt.datetime, end_date: dt.datetime) -> str:
        """
        Returns an IB-compatible duration string based on the time span
        between start_date and end_date.

        - If <= 365 days, returns "XXX D"
        - If > 365 days, returns "Y Y" (years),
          where Y is the ceiling of the number of 365-day chunks.
        """
        delta_days = (end_date - start_date).days

        # IB error 321: "Historical data requests for durations longer than 365 days must be made in years."
        if delta_days <= 365:
            # e.g., "300 D"
            return f"{delta_days} D"
        else:
            # e.g., "2 Y" if 370 days
            years = math.ceil(delta_days / 365.0)
            return f"{years} Y"

    @staticmethod
    def preprocess_historical_data(data):

        df = util.df(data)
        if df is None or df.empty:
            return pd.DataFrame()

        # Rename columns to a standard format
        df.rename(columns={'date': 'Date', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)

        df.set_index('Date', inplace=True)
        df.sort_index(inplace=True)
        df.index = pd.DatetimeIndex(df.index)
        return df

    @staticmethod
    def get_exchange_timezone(exchange: str) -> str:
        """
        Return the appropriate time zone suffix for endDateTime, for the fetch_historical_data function.
        based on the exchange. If not found, either return '' or
        a default (e.g. 'US/Eastern').
        """
        exchange_tz_map = {
            'SMART': 'US/Eastern',
            'NYSE': 'US/Eastern',
            'NASDAQ': 'US/Eastern',
            'AEB': 'Europe/Amsterdam',
            'SBF': 'Europe/Paris',
            'IBIS': 'Europe/Berlin',
            'BVME': 'Europe/Rome',
            'LSE': 'Europe/London',
            'SEHK': 'Asia/Hong_Kong',
            'TSE': 'Asia/Tokyo',
            'ATH': 'Europe/Athens',
        }
        return exchange_tz_map.get(exchange, '')

    def group_by_symbol(self, items) -> Dict[str, List[object]]:
        """
        Helper method to group objects by their contract.symbol.
        :param items: A list of objects that must have `.contract.symbol`.
        :return: Dictionary { 'SYMBOL': [item, item, ...], ... }
        """
        grouped = {}
        for item in items:
            symbol = item.contract.symbol
            if symbol not in grouped:
                grouped[symbol] = []
            grouped[symbol].append(item)
        return grouped
