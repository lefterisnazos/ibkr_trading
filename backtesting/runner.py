# main.py

from backtester_app import BacktesterApp
from backtesting.strategies.OpenRangeBreakout import OpenRangeBreakout
from backtester import Backtester

if __name__ == "__main__":
    # 1) Initialize IB environment
    app = BacktesterApp(host='127.0.0.1', port=7497, clientId=24)

    # 2) Define ticker universe
    tickers = ["AAPL", "TSLA", "IBKR"]

    # 3) Create the strategy
    strategy = OpenRangeBreakout()

    # 4) Create & run backtester
    backtester = Backtester(strategy=strategy, app=app, tickers=tickers)
    backtester.run()

    # 5) Evaluate
    backtester.evaluate()

    # You can also retrieve the trades DataFrame:
    trades_df = backtester.trades_df
    # do further analysis, e.g. trades_df.to_csv("trades_log.csv")
