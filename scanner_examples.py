from ib_opn_rng_brkout import TradeApp
from ibapi.scanner import *
from ibapi.client import EClient
from ibapi.wrapper import EWrapper

app = TradeApp()

def create_scanner_subscription(instrument="STK", location_code="STK.US", scan_code="TOP_PERC_GAIN"):
    subscription = ScannerSubscription()
    subscription.instrument = instrument  # Financial instrument (e.g., stocks)
    subscription.locationCode = location_code  # Geographic region/market
    subscription.scanCode = scan_code  # Scan type (e.g., top percentage gainers)
    return subscription

us_stocks_high_volume = create_scanner_subscription(instrument="STK", location_code="STK.US", scan_code="HOT_BY_VOLUME")

# Scanner for EU stocks, top gainers
eu_stocks_top_gainers = create_scanner_subscription(instrument="STK", location_code="STK.EU", scan_code="TOP_PERC_GAIN")

# scanner subsd with different params
app.reqScannerSubscription(1, us_stocks_high_volume, [], [])
app.reqScannerSubscription(2, eu_stocks_top_gainers, [], [])