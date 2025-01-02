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
        return df
