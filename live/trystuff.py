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