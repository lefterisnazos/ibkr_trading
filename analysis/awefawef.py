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

contract = Stock('AAPL', 'SMART', 'USD')

# Request contract details
details = ib.ib.reqContractDetails(contract)
if details:
    cd = details[0]
    print("Regular Trading Hours:")
    print(cd.tradingHours)
    print("\nLiquid Hours:")
    print(cd.liquidHours)
else:
    print("No contract details returned.")



end_dt = dt.datetime.now().strftime("%Y%m%d %H:%M:%S")
bars = ib.ib.reqHistoricalData(
    contract=contract,
    endDateTime=end_dt,
    durationStr="3 D",
    barSizeSetting="1 min",
    whatToShow="TRADES",
    useRTH=False,    # Request data for the full day including extended hours
    formatDate=1
)

if bars:
    df = ib.util.df(bars)
    print(df.tail())
else:
    print("No bars returned. Extended hours data may not be available.")