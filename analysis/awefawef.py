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
start = dt.datetime(2025, 3, 1)
end = dt.datetime(2025, 3, 17)
data = ib.fetch_historical_data('THEON', start, end, bar_size='1 hour')
x=2