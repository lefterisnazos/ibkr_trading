from backtesting.benchmarks.benchmarks import (
    AbsoluteReturnEvaluation,
    WinRateEvaluation,
    MeanReturnWinner,
    MeanReturnLoser
)


class Backtester:
    """
    Orchestrates the entire backtest pipeline:
      - Prepare data
      - Run strategy
      - Evaluate results
    """
    def __init__(self, strategy, app, tickers):
        self.strategy = strategy  # must be a BaseStrategy or derived
        self.app = app           # IB environment
        self.tickers = tickers
        self.data = None         # store daily data or any other data needed
        self.results = None      # store results from strategy

    def run(self):
        # 1. Prepare data
        self.data = self.strategy.prepare_data(self.app, self.tickers)

        # 2. Run strategy
        self.results = self.strategy.run_strategy(self.app, self.data)

    def evaluate(self):
        # Evaluate using multiple metrics
        absolute_ret = AbsoluteReturnEvaluation().compute(self.results)
        win_rate = WinRateEvaluation().compute(self.results)
        mean_win = MeanReturnWinner().compute(self.results)
        mean_loss = MeanReturnLoser().compute(self.results)

        print("**********Strategy Performance Statistics**********")
        print(f"Total cumulative return: {round(absolute_ret, 4)}")
        print(f"Total win rate         : {round(win_rate, 2)}%")
        print(f"Mean return (winners)  : {round(mean_win, 4)}")
        print(f"Mean return (losers)   : {round(mean_loss, 4)}")