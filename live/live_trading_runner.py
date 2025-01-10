import schedule
import time
from ib_client_live import *
import datetime as dt
from ib_insync import IB, RealTimeBarList

class LiveRunner:
    def __init__(self, strategy):
        self.strategy = strategy
        self.ib_c = strategy.ib_c  # convenience
        self.ib = self.ib_c.ib
        self.ib_c.connect()

        self.ib_c.account = "DU8057891"
        self.tickers = ["MSFT"]
        self.strategy.tickers = self.tickers

        self.rtbars = {}             # {ticker: RealTimeBarList}
        self.last_prepared_day = None
        self.subscribed = False       # To track if we've subscribed already today

    def start(self):
        """
        1) Schedule market_open at e.g. 09:25 M-F
        2) Schedule market_close at e.g. 16:25 M-F
        3) Schedule on_schedule_tick every X minutes
        4) Enter main loop
        """
        for weekday in (schedule.every().monday, schedule.every().tuesday, schedule.every().wednesday, schedule.every().thursday, schedule.every().friday):
            weekday.at("09:31").do(self.on_market_open)
            weekday.at("16:25").do(self.on_market_close)

        # For example, run on_schedule_tick every 5 minutes
        schedule.every(1).minutes.do(self.on_schedule_tick)

        while True:
            schedule.run_pending()
            self.ib.sleep(1)

    def on_market_open(self):
        """
        Called once each weekday at 09:25 (example).
        Only connect to IB here, so we're ready for trading.
        """
        print(f"[{dt.datetime.now()}] on_market_open: Connecting to IB.")
        self.ib_c.connect()

        # Reset states for the new day
        self.subscribed = False
        print("[LiveRunner] Market open: connected, ready for schedule ticks.")

    def on_schedule_tick(self):
        if not self.ib.isConnected():
            self.ib_c.connect()
            self.ib.sleep(1)

        today = dt.date.today()
        if self.last_prepared_day != today:
            print("[LiveRunner] New day => prepare_data.")
            self.strategy.prepare_data(self.tickers)
            self.last_prepared_day = today

        # Subscribe to live bars if not already subscribed
        # (Adjust logic as needed; this is just an example.)
        if not self.subscribed:
            self.subscribed = True
            for ticker in self.tickers:
                contract = self.ib_c.us_tech_stock(ticker)

                # Request last 10 minutes of bars, 5-second resolution
                bars = self.ib.reqHistoricalData(contract,
                        endDateTime='',
                        durationStr='15 mins',
                        barSizeSetting='1 min',
                        whatToShow='MIDPOINT',
                        useRTH=False,
                        formatDate=1, keepUpToDate=True)

                # store the BarDataList in a dict so we can cancel later
                self.rtbars[ticker] = bars

                # Attach the callback via a lambda capturing `ticker`
                bars.updateEvent += lambda b_, new, t=ticker: self.onBarUpdate(b_, new, t)
                self.ib.sleep(10)
                self.ib.cancelHistoricalData(bars)

    def onBarUpdate(self, bars_: RealTimeBarList, hasNewBar: bool, ticker: str):
        """
        The updateEvent from ib_insync BarDataList passes two arguments:
          bars_ (BarDataList) and hasNewBar (bool).
        We capture 'ticker' separately via a lambda default.
        """

        bars_ = IBClientLive.preprocess_historical_data(bars_)
        if hasNewBar and bars_:
            latest_bar = bars_[-1]
            open_px = latest_bar.open
            bar_ts = latest_bar.time

            print(f"[on_realtime_bar] {ticker} at {bar_ts}, open={open_px}")

            self.strategy.on_new_bar(ticker, open_px, bar_ts, volume=1)

    def on_market_close(self):
        print(f"[{dt.datetime.now()}] on_market_close: Flatten/Disconnect.")

        # Cancel all real-time bars
        for ticker, bars_list in self.rtbars.items():
            self.ib.cancelHistoricalData(bars_list)
        self.rtbars.clear()
        self.subscribed = False

        # Disconnect
        if self.ib.isConnected():
            self.ib_c.disconnect()
        print("[LiveRunner] Market close: disconnected.")
