# main.py

from backtester_app import BacktesterApp
from backtesting.strategies.OpenRangeBreakout import OpenRangeBreakout
from backtester import Backtester

if __name__ == "__main__":
    # 1) Initialize IB connection environment
    app = BacktesterApp(host='127.0.0.1', port=7497, clientId=24)

    # 2) Define ticker universe
    tickers = ["AAPL", "TSLA", "IBKR"]

    # 3) Create the strategy
    strategy = OpenRangeBreakout()

    # 4) Create and run the backtester
    backtester = Backtester(strategy=strategy, app=app, tickers=tickers)
    backtester.run()

    # 5) Evaluate performance
    backtester.evaluate()
