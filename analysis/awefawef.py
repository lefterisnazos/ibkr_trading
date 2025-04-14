import time
import datetime as dt
import pandas as pd
from ib_insync import IB, Stock, util, Fill, Trade as IBTrade
from live.ib_client_live import IBClientLive
import math
from typing import Dict, List, Tuple, Optional
from tqdm import tqdm

from ib_insync import MarketOrder, LimitOrder, StopOrder, Order, BracketOrder, Trade, Position

ib = IBClientLive(account='DU8057891', client_id=30)
ib.connect()

import math
from ib_insync import IB, Stock, LimitOrder

# Define an error handling callback function.
def error_handler(reqId, errorCode, errorString, advancedOrderRejectJson):
    if "fractional" in errorString.lower():
        print("Fractional error detected:", errorString)

# Create an IB instance and attach the error event handler.
ib = IB()
ib.errorEvent += error_handler

# Connect to IBKR. Adjust host, port, and clientId as necessary.
ib.connect('127.0.0.1', 7497, clientId=33)

# Define a stock contract for AAPL.
contract = Stock('THEON', 'SMART', 'EUR')

# Create a limit order with a fractional quantity.
fractionQuantity = 1.5  # Fractional share quantity
order = LimitOrder('BUY', fractionQuantity, 24.5)

# Place the order.
trade = ib.placeOrder(contract, order)

# Sleep a few seconds to allow any asynchronous error messages to be delivered.
ib.sleep(3)

# Disconnect after processing.
ib.disconnect()