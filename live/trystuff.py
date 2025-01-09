from backtesting.ib_client import IBClient
from ib_client_live import *
from ib_insync import MarketOrder, LimitOrder, StopOrder, Order, BracketOrder, Trade, Position
from ib_insync import IB, Stock, util, Fill, Trade as IBTrade

from ib_insync import IB, util

ib = IB()
ib.connect()  # Make sure you're connecting to TWS or IB Gateway
client = IBClient()
contract = client.us_tech_stock(symbol="MSFT")

rtb = ib.reqRealTimeBars(
    contract,
    barSize=5,
    whatToShow='TRADES',
    useRTH=True
)

def onBarUpdate(bars, hasNewBar):
    print("New real-time bar:", bars[-1])

# Subscribe to the 'updateEvent' on the RealTimeBarList
rtb.updateEvent += onBarUpdate

# Keep the script running to allow data to stream
ib.run()


x=2
y=2


def on_market_open(self):
     print("[LiveRunner] Market open logic.")
     self.strategy.connect_to_ib()

     # 1) Prepare daily data + compute LR lines
     self.strategy.prepare_data(self.tickers)

     # 2) Subscribe to real-time bars
     for symbol in self.tickers:
          contract = self.ib_client.us_tech_stock(symbol)
          rtb = self.ib.reqRealTimeBars(contract, barSize=5, whatToShow='TRADES', useRTH=True)
          self.rtbars[symbol] = rtb

     # 3) Register a barUpdateEvent callback for each rtb
     for symbol, rtb in self.rtbars.items():
          rtb.updateEvent += lambda bars, sym=symbol: self.on_realtime_bar(sym, bars)


def on_realtime_bar(self, ticker: str, bars: RealTimeBarList):
     # The most recent bar is bars[-1]
     if not bars:
          return
     latest_bar = bars[-1]  # an ib_insync RealTimeBar object
     open_px = latest_bar.open
     bar_ts = latest_bar.time  # datetime

     # Call our strategy’s on_new_bar method
     self.strategy.on_new_bar(ticker, open_px, bar_ts, volume=1)