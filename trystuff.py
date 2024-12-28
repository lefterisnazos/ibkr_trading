from ib_insync import *
# util.startLoop()  # uncomment this line when in a notebook
from ibapi.contract import Contract
import time


def create_nasdaq_contract(symbol):
    """Create a contract object for a NASDAQ-listed stock."""
    contract = Contract()
    contract.symbol = symbol  # Replace with any NASDAQ stock symbol
    contract.secType = "STK"  # Security type: Stock
    contract.exchange = "SMART"  # Use SMART routing for NASDAQ stocks
    contract.primaryExchange = "NASDAQ"  # Specify NASDAQ as primary
    contract.currency = "USD"  # Stock is priced in USD
    return contract


ib = IB()
ib.connect('127.0.0.1', 7497, clientId=24)

contract = create_nasdaq_contract('AAPL')
bars=  ib.reqHistoricalData(
    contract, endDateTime='', durationStr='30 D',
    barSizeSetting='1 hour', whatToShow='MIDPOINT', useRTH=True)

# Wait for data to be fetched
time.sleep(1)

# convert to pandas dataframe (pandas needs to be installed):
df = util.df(bars)
print(df)