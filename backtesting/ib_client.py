import time
import datetime as dt
import pandas as pd
from ib_insync import IB, Stock, util

class IBClient:
    """
    Encapsulates all IB connection and data-fetching logic using ib_insync.
    """

    def __init__(self, host='127.0.0.1', port=7497, client_id=25):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()

    def connect(self):
        """
        Connect to the IB TWS/Gateway using ib_insync.IB.
        """
        try:
            self.ib.connect(
                host=self.host,
                port=self.port,
                clientId=self.client_id
            )
            print("Connected to IB.")
        except Exception as e:
            print(f"Could not connect to IB: {e}")

    def disconnect(self):
        """
        Disconnect from IB.
        """
        self.ib.disconnect()
        print("Disconnected from IB.")

    def us_tech_stock(self, symbol: str, exchange: str = 'SMART', currency: str = 'USD'):
        """
        Create an ib_insync Stock contract for a US equity.
        """
        return Stock(symbol, exchange=exchange, currency=currency)

    def fetch_historical_data(self, symbol: str, end_date: dt.datetime, duration_str: str, bar_size: str, what_to_show: str = 'TRADES', use_rth: bool = True) -> pd.DataFrame:
        """
        Uses ib_insync to request historical data for `symbol` as a DataFrame.
        :param symbol: Ticker symbol (e.g., 'AAPL').
        :param end_date: End datetime (Python `datetime`) for the historical data request.
        :param duration_str: IB-compatible duration string, e.g. "1 Y", "1 D", etc.
        :param bar_size: IB-compatible bar size, e.g. "1 day", "5 mins".
        :param what_to_show: 'TRADES', 'MIDPOINT', etc.
        :param use_rth: Whether to use regular trading hours only.
        :return: DataFrame with columns: [Date, Open, High, Low, Close, Volume, ...]
        """
        contract = self.us_tech_stock(symbol)
        end_date_str = end_date.strftime("%Y%m%d %H:%M:%S") + " US/Eastern"

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
        df.rename(columns={
            'date': 'Date',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        }, inplace=True)

        df.set_index('Date', inplace=True)
        df.sort_index(inplace=True)
        df.index = pd.DatetimeIndex(df.index)
        return df

    def fetch_intraday_in_chunks(self, ticker: str, start: pd.Timestamp, end: pd.Timestamp, bar_size: str = "5 mins", chunk_size_request: str = "2 M") -> pd.DataFrame:
        """
        Fetch all intraday data for 'ticker' from 'start' to 'end',
        in 'chunk_size_request' chunks (e.g. '2 M' => 2 months),
        and concatenate into a single DataFrame.

        :param ticker: The symbol (e.g. "AAPL").
        :param start:  A pandas Timestamp or datetime representing the earliest date/time.
        :param end:    A pandas Timestamp or datetime representing the latest date/time.
        :param bar_size: e.g. "5 mins"
        :param chunk_size_request: e.g. "2 M", "1 D", "3 W". Any IB-compatible duration string.
        :return: A DataFrame of intraday bars in [start, end].
        """

        chunks = []
        current_end = end

        # We'll iterate backward from 'end' until we reach 'start'
        while current_end > start:

            df_chunk = self.fetch_historical_data(symbol=ticker, end_date=current_end,  duration_str=chunk_size_request, bar_size=bar_size, what_to_show='TRADES', use_rth=True)

            if df_chunk.empty:
                break

            chunks.append(df_chunk)

            # Identify the earliest time in this chunk
            earliest_in_chunk = df_chunk.index.min().tz_localize(None)
            if earliest_in_chunk >= current_end:
                # We didn't get older data => nothing left
                break

            # Move current_end to just before earliest_in_chunk
            # so next request fetches older data
            # e.g. subtract 1 bar or a few minutes buffer
            current_end = earliest_in_chunk - pd.Timedelta(minutes=5)

        if not chunks:
            return pd.DataFrame()

        # Concatenate
        all_intraday = pd.concat(chunks)
        all_intraday.sort_index(inplace=True)
        all_intraday = all_intraday[~all_intraday.index.duplicated(keep='first')]

        start = start.tz_localize('US/Eastern')  # or .tz_convert(...)
        end = end.tz_localize('US/Eastern')

        return all_intraday[(all_intraday.index >= start) & (all_intraday.index <= end)]

# ib = IBClient()
# ib.connect()
# timestamp = pd.Timestamp('2024-01-02 22:05:00')
# x1 = time.time()
# intraday_df = ib.fetch_historical_data(symbol='JAZZ', end_date=timestamp, duration_str='25 D', bar_size='5 mins')
# y1= time.time()
#
# x2 = time.time()
# for _ in range(25):
#
#     intraday_df = ib.fetch_historical_data(symbol='JAZZ', end_date=timestamp, duration_str='1 D', bar_size='5 mins')
# y2 = time.time()
#
# diff1 = y1- x1
# diff2  = y2-x2
z=2

