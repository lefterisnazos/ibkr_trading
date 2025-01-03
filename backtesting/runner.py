# main.py
from tqdm import tqdm

from backtester_app import BacktesterApp
from backtesting.strategies.OpenRangeBreakout import OpenRangeBreakout
from backtesting.strategies.LinearRegSigmaStrategy import LinRegSigmaStrategy
from backtester import Backtester
import datetime as dt

if __name__ == "__main__":

    # 2) Define ticker universe
    tickers = ['JAZZ']

    # 3) Start & end date for backtest
    start_date = dt.datetime(2024, 1, 1)
    end_date = dt.datetime(2024, 10, 1)

    # 4) Instantiate the strategy
    strategy = LinRegSigmaStrategy(start_date, end_date, medium_lookback=30, long_lookback=150)

    # 5) Instantiate the backtester with date range
    backtester = Backtester(
        strategy=strategy,
        tickers=tickers
    )

    # 6) Run the backtest
    backtester.run()

    # 7) Evaluate results
    stats = backtester.evaluate()