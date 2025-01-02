import time
import threading
import pandas as pd

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract


class BacktesterApp(EWrapper, EClient):
    """
    This class manages:
      - The IB connection
      - Any threading events (e.g., for historical data)
      - Internal data structures for storing data returned from IB
      - Error handling to skip further requests if needed
    """
    def __init__(self, host='127.0.0.1', port=7497, clientId=25):
        EClient.__init__(self, self)

        self.host = host
        self.port = port
        self.clientId = clientId
        self.thread = None

        # Dictionary to store data: {reqId: DataFrame of bars}
        self.data = {}

        # This flag can be used to skip logic if the IB API returns an error for a specific request
        self.skip = False

        # Threading event used to signal that a ticker's data request is complete

        self.ticker_event = threading.Event()
        self.currentReqId = 0

        # Start the IB connection in a background thread
        self.connect_and_start()


    def connect_and_start(self):
        """
        Connect to IB TWS/Gateway and start the EClient processing loop in a dedicated thread.
        """
        self.connect(self.host, self.port, self.clientId)

        # The EClient.run() method processes incoming messages
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

        # Give it a moment to establish connection
        time.sleep(3)

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=''):
        """
        Overridden error handler from EWrapper.
        If there's an error for a specific request ID, we set 'skip' to True
        and notify the thread waiting on ticker_event.
        """
        print(f"Error. ReqId: {reqId}, Code: {errorCode}, Msg: {errorString}")
        if errorCode!= 2176:
            self.skip = True
            print("skipping calculations")
        self.ticker_event.set()
        self.currentReqId +=1

    def historicalData(self, reqId, bar):
        if reqId not in self.data:
            self.data[reqId] = pd.DataFrame([{"Date":bar.date,"Open":bar.open,"High":bar.high,"Low":bar.low,"Close":bar.close,"Volume":bar.volume}])
        else:
            self.data[reqId] = pd.concat((self.data[reqId],pd.DataFrame([{"Date":bar.date,"Open":bar.open,"High":bar.high,"Low":bar.low,"Close":bar.close,"Volume":bar.volume}])))

    def historicalDataEnd(self, reqId, start, end):
        super().historicalDataEnd(reqId, start, end)

        df = self.data.get(reqId, None)
        if df is not None and not df.empty:
            sample = df.iloc[0]["Date"]  # Just check the first row to guess format

            if isinstance(sample, (int, float)):
                # Likely older intraday => parse as Unix epoch (seconds)
                df["Date"] = pd.to_datetime(df["Date"], unit="s", origin="unix")

            elif isinstance(sample, str):
                if " " in sample:
                    # Format is yyyymmdd HH:MM:SS
                    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d  %H:%M:%S", errors="coerce")
                else:
                    # Format is yyyymmdd (daily bars)
                    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d", errors="coerce")

            # Now set as index & sort
            df.set_index("Date", inplace=True)
            df.sort_index(inplace=True)

            self.data[reqId] = df

        print("HistoricalDataEnd. ReqId:", reqId, "from", start, "to", end)

        self.skip = False
        self.ticker_event.set()

def usTechStk(symbol, sec_type="STK", currency="USD", exchange="ISLAND"):
    contract = Contract()
    contract.symbol = symbol
    contract.secType = sec_type
    contract.currency = currency
    contract.exchange = exchange
    return contract

def histData(app: BacktesterApp, req_num, contract, endDate, duration, candle_size, format_date=1):
    """extracts historical data"""
    app.reqHistoricalData(reqId=req_num,
                          contract=contract,
                          endDateTime=endDate,
                          durationStr=duration,
                          barSizeSetting=candle_size,
                          whatToShow='TRADES',
                          useRTH=1,
                          formatDate=format_date,
                          keepUpToDate=0,
                          chartOptions=[])


def dataDataframe(symbols, app: BacktesterApp):
    """
    Convert the collected raw data in app.data to a dictionary of DataFrames.
    Keys are ticker symbols, values are DataFrames with historical data.
    """
    df_data = {}
    for symbol in symbols:
        req_id = symbols.index(symbol)  # or a mapping
        df_data[symbol] = pd.DataFrame(app.data.get(req_id, []))
        df_data[symbol].set_index("Date", inplace=True)
    return df_data