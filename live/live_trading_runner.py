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

        # Connect once at init, or you can skip here and only connect at market open.
        self.ib_c.connect()

        self.ib_c.account = "DU8057891"
        self.tickers = ["MSFT"]
        self.strategy.tickers = self.tickers

        # For storing subscriptions so we can cancel later
        self.force_start = True
        self.rtbars = {}
        self.last_prepared_day = None
        self.subscribed = False

    def start(self):
        """
        1) Schedule market_open for 09:31 M-F
        2) Schedule market_close for 16:25 M-F
        3) Enter main loop
        """

        for weekday in (
            schedule.every().monday,
            schedule.every().tuesday,
            schedule.every().wednesday,
            schedule.every().thursday,
            schedule.every().friday
        ):
            weekday.at("09:31").do(self.on_market_open)
            weekday.at("16:25").do(self.on_market_close)

        if self.force_start:
            self.on_market_open()

        # main event loop
        while True:
            schedule.run_pending()
            self.ib.sleep(5)

    def on_market_open(self):
        """
        Called once each weekday at 09:31.
        Connect to IB (if not already connected), prepare data, subscribe to bars.
        """
        print(f"[{dt.datetime.now()}] on_market_open: Connecting to IB.")
        if not self.ib.isConnected():
            self.ib_c.connect()

        # If it’s a new day, prepare data once
        today = dt.date.today()
        if self.last_prepared_day != today:
            print("[LiveRunner] New day => prepare_data.")
            self.strategy.prepare_data(self.tickers)
            self.last_prepared_day = today

        # Subscribe to real-time bars once per day
        if not self.subscribed:
            self.subscribed = True
            for ticker in self.tickers:
                contract = self.ib_c.us_tech_stock(ticker)

                # This subscription gives you a bar every 1 minute
                bars = self.ib.reqHistoricalData(
                    contract,
                    endDateTime='',
                    durationStr='600 S',   # get initial 10 minutes of data for context
                    barSizeSetting='5 min',
                    whatToShow='MIDPOINT',
                    useRTH=True,
                    formatDate=1,
                    keepUpToDate=True
                )

                self.rtbars[ticker] = bars

                # Attach a callback that fires once a new bar completes
                bars.updateEvent += lambda b_, new, t=ticker: self.onBarUpdate(b_, new, t)

        print("[LiveRunner] Market open: Subscribed to real-time bars.")

    def on_market_close(self):
        """
        Called once each weekday at 16:25.
        Cancel real-time subscriptions, possibly flatten positions, and disconnect.
        """
        print(f"[{dt.datetime.now()}] on_market_close: Flatten/Disconnect.")

        # Cancel subscriptions
        for ticker, bars_list in self.rtbars.items():
            self.ib.cancelHistoricalData(bars_list)
        self.rtbars.clear()
        self.subscribed = False

        # Disconnect from IB
        if self.ib.isConnected():
            self.ib_c.disconnect()

        print("[LiveRunner] Market close: disconnected.")

    def onBarUpdate(self, bars_: RealTimeBarList, hasNewBar: bool, ticker: str):
        """
        Called automatically when IB completes a new 1-minute bar (because barSizeSetting='1 min').
        """
        if hasNewBar and bars_:
            latest_bar = bars_[-1]
            open_px = latest_bar.open
            bar_ts = latest_bar.time

            print(f"[on_realtime_bar] {ticker} at {bar_ts}, open={open_px}")

            # Pass the bar on to your strategy
            self.strategy.on_new_bar(ticker, open_px, bar_ts, volume=latest_bar.volume)
