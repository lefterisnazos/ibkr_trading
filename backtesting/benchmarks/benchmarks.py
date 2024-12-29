import pandas as pd

class EvaluationMetric:
    """
    Base class for evaluation metrics.
    Subclasses should implement compute(date_stats) -> float or dict.
    """
    def compute(self, date_stats):
        raise NotImplementedError("Subclasses must implement this method.")



class AbsoluteReturnEvaluation(EvaluationMetric):
    """
    Computes total cumulative return from the date_stats dictionary.
    date_stats is assumed to be: {date: {ticker: return_float}}
    """
    def compute(self, date_stats):
        df = pd.DataFrame(date_stats).T  # columns = tickers, index = date
        df["ret"] = 1 + df.mean(axis=1)   # daily average return
        cum_ret = (df["ret"].cumprod() - 1)[-1]
        return cum_ret


class WinRateEvaluation(EvaluationMetric):
    """
    Computes the overall win rate across all trades.
    """
    def compute(self, date_stats):
        win_count, lose_count = 0, 0
        for d in date_stats:
            for tkr in date_stats[d]:
                if date_stats[d][tkr] > 0:
                    win_count += 1
                elif date_stats[d][tkr] < 0:
                    lose_count += 1
        if (win_count + lose_count) == 0:
            return 0.0
        return win_count / (win_count + lose_count) * 100


class MeanReturnWinner(EvaluationMetric):
    """
    Mean return of winning trades.
    """
    def compute(self, date_stats):
        winners = []
        for d in date_stats:
            for tkr in date_stats[d]:
                if date_stats[d][tkr] > 0:
                    winners.append(date_stats[d][tkr])
        return sum(winners)/len(winners) if len(winners) > 0 else 0


class MeanReturnLoser(EvaluationMetric):
    """
    Mean return of losing trades.
    """
    def compute(self, date_stats):
        losers = []
        for d in date_stats:
            for tkr in date_stats[d]:
                if date_stats[d][tkr] < 0:
                    losers.append(date_stats[d][tkr])
        return sum(losers)/len(losers) if len(losers) > 0 else 0
