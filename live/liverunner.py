import schedule
import time
from ib_insync import IB, util, RealTimeBarList
import datetime as dt


class LiveRunner:
    def __init__(self, strategy):
        self.strategy = strategy
        self.ib_client = strategy.ib_client
        self.ib_client.account = "DU8057891"
        self.ib = self.ib_client.ib  # convenience

        self.tickers = ["AAPL", "MSFT"]
        self.strategy.tickers = self.tickers# or pass them in

        # For storing RealTimeBarList objects
        self.rtbars = {}  # {ticker: RealTimeBarList}

    def start(self):
        # Schedule tasks (or you can just run a continuous loop)
        schedule.every().monday.at("09:25").do(self.on_market_open)
        schedule.every().tuesday.at("09:25").do(self.on_market_open)

        schedule.every().day.at("15:50").do(self.on_market_close)

        while True:
            schedule.run_pending()
            self.ib.sleep(1)

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

    def on_market_close(self):
        print("[LiveRunner] Market close logic. Flatten positions if needed.")
        # Example: Flatten any open positions
        for ticker, pos in self.strategy.position.items():
            if pos is not None and pos.volume > 0:
                side_to_close = "SELL" if pos.side == "B" else "BUY"
                self.strategy.place_live_trade(ticker, side=side_to_close, qty=pos.volume, ref_price=0.0)

        self.strategy.disconnect_from_ib()