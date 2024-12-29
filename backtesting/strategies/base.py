from abc import ABC, abstractmethod
import pandas as pd
import time


class BaseStrategy(ABC):
    """
    A base class to standardize strategy structure.
    """

    @abstractmethod
    def prepare_data(self, env, tickers):
        """
        1) Possibly retrieve initial data
        2) Build or transform data
        """
        pass

    @abstractmethod
    def run_strategy(self, env, data):
        """
        Implement the core logic of the strategy, returning date_stats or performance.
        """
        pass