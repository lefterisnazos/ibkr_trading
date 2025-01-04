# main.py

from backtesting.strategies.LinearRegSigmaStrategy import LinRegSigmaStrategy
from backtester import Backtester
import datetime as dt

if __name__ == "__main__":

    # 2) Define ticker universe
    tickers = ['QQQ']

    # 3) Start & end date for backtest
    start_date = dt.datetime(2024, 1, 1)
    end_date = dt.datetime(2024, 3, 1)

    # 4) Instantiate the strategy
    strategy = LinRegSigmaStrategy(start_date, end_date, medium_lookback=22, long_lookback=88)

    # 5) Instantiate the backtester with date range
    backtester = Backtester(
        strategy=strategy,
        tickers=tickers
    )

    # 6) Run the backtest
    backtester.run()

    # 7) Evaluate results
    stats = backtester.evaluate()