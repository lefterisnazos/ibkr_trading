import schedule
import time
import datetime as dt
from ib_insync import IB, RealTimeBarList

class LiveRunner:
    def __init__(self, strategy):
        self.strategy = strategy
        self.ib_c = strategy.ib_c  # convenience
        self.ib = self.ib_c.ib

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
        schedule.every().week().at("09:31").do(self.on_market_open)
        schedule.every().week().at("16:25").do(self.on_market_close)

        # For example, run on_schedule_tick every 5 minutes
        schedule.every(1).minutes.do(self.on_schedule_tick)

        while True:
            schedule.run_pending()
            time.sleep(1)

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
        """
        Called every 5 minutes (example).
        1) If it's a new day, run 'prepare_data' once.
        2) If not yet subscribed, subscribe to real-time bars and attach callbacks.
        """
        # If not connected, do nothing
        if not self.ib.isConnected():
            self.ib_c.connect()

        # 1) Check if date changed => retrain daily
        today = dt.date.today()
        if self.last_prepared_day != today:
            print("[LiveRunner] New day => prepare_data.")
            self.strategy.prepare_data(self.tickers)
            self.last_prepared_day = today
            self.subscribed = False  # reset so we can re-subscribe once per new day

        # 2) Subscribe to real-time bars only if not already done this day
        if not self.subscribed:
            print("[LiveRunner] Subscribing to real-time bars for tickers...")
            for ticker in self.tickers:
                contract = self.ib_c.us_tech_stock(ticker)
                rtb = self.ib.reqRealTimeBars(
                    contract,
                    barSize=5,
                    whatToShow='MIDPOINT',
                    useRTH=False
                )
                self.rtbars[ticker] = rtb

                # Attach callback properly, using lambda or partial
                rtb.updateEvent += (lambda bars, hasNewBar, sym=ticker:
                                    self.on_realtime_bar(sym, bars))

            self.subscribed = True

    def on_realtime_bar(self, ticker: str, bars: RealTimeBarList):
        """
        Called automatically whenever a new or updated bar arrives for 'ticker'.
        """
        if not bars:
            return
        latest_bar = bars[-1]
        open_px = latest_bar.open
        bar_ts = latest_bar.time
        print(f"[on_realtime_bar] {ticker} at {bar_ts}, open={open_px}")

        # Forward to strategy
        self.strategy.on_new_bar(ticker, open_px, bar_ts, volume=1)

    def on_market_close(self):
        """
        Called once each weekday at 16:25 (example).
        1) Optionally flatten positions.
        2) Cancel real-time bars.
        3) Disconnect.
        """
        print(f"[{dt.datetime.now()}] on_market_close: Flatten/Disconnect.")

        for ticker, bars_list in self.rtbars.items():
            self.ib.cancelRealTimeBars(bars_list)
        self.rtbars.clear()
        self.subscribed = False

        # Disconnect
        if self.ib.isConnected():
            self.ib_c.disconnect()
        print("[LiveRunner] Market close: disconnected.")
