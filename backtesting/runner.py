# main.py

from backtester_app import BacktesterApp
from backtesting.strategies.OpenRangeBreakout import OpenRangeBreakout
from backtesting.strategies.LinearRegSigmaStrategy import LinRegSigmaStrategy
from backtester import Backtester
import datetime as dt

if __name__ == "__main__":
    # 1) Initialize IB environment
    app = BacktesterApp(host='127.0.0.1', port=7497, clientId=26)

    # 2) Define ticker universe
    tickers = ["AAPL", "TSLA", "IBKR"]

    # 3) Start & end date for backtest
    start_date = dt.datetime(2024, 1, 1)
    end_date = dt.datetime(2024, 6, 1)

    # 4) Instantiate the strategy
    strategy = LinRegSigmaStrategy(start_date, end_date)

    # 5) Instantiate the backtester with date range
    backtester = Backtester(
        strategy=strategy,
        app=app,
        tickers=tickers
    )

    # 6) Run the backtest
    backtester.run()

    # 7) Evaluate results
    stats = backtester.evaluate()