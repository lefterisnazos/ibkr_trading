from backtesting.ib_client import IBClient
from ib_client_live import *
from ib_insync import MarketOrder, LimitOrder, StopOrder, Order, BracketOrder, Trade, Position
from ib_insync import IB, Stock, util, Fill, Trade as IBTrade

client = IBClient()
client.connect()

contract = client.us_tech_stock('AAPL')

ib = client.ib

g = ib.positions()
bracket_orders = ib.bracketOrder(action='BUY', quantity=1, limitPrice=200, takeProfitPrice=250, stopLossPrice=180)
for order in bracket_orders:
     ib.placeOrder(contract, order)

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