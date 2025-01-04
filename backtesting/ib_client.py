import time
import datetime as dt
import pandas as pd
from ib_insync import IB, Stock, util
import math
from tqdm import tqdm
from rich.progress import Progress, BarColumn, TimeElapsedColumn, TimeRemainingColumn, TaskID

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
        contract = self.us_tech_stock(symbol)
        duration_str = IBClient.get_ib_duration_str(start_date, end_date)
        end_date_str = end_date.strftime("%Y%m%d %H:%M:%S") + " US/Eastern"
        #print('Fetching historical data for', symbol, 'from', start_date, 'to', end_date, '...', end='')
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

        with Progress("[progress.description]{task.description}", BarColumn(), "[progress.percentage]{task.percentage:>3.0f}%", "•", TimeElapsedColumn(), "•",
                TimeRemainingColumn(), ) as progress:

            task_id: TaskID = progress.add_task(f"Fetching intraday for {ticker}", total=estimated_chunks)

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
                progress.update(task_id, advance=1)


                # If subperiod_start == start => done
                if current_start == start:
                    break

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
