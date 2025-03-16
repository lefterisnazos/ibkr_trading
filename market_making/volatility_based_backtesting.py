import math
import time
import numpy as np
import pandas as pd
from ib_insync import IB, Stock, LimitOrder, util
from market_making.volatility_based import VolatilityMarketMaker, RiskManager


# (Your RiskManager and VolatilityMarketMaker classes from above go here.)
# ----------------------------------------------
# Assume the RiskManager and VolatilityMarketMaker classes are defined as in your code.
# ----------------------------------------------

class BacktestEngine:
    """
    A simple backtesting engine for the market making strategy.
    It simulates a data feed from historical bars and uses a simplified fill simulation.
    """

    def __init__(self, market_maker: VolatilityMarketMaker, historical_data: pd.DataFrame):
        """
        :param market_maker: An instance of your VolatilityMarketMaker.
        :param historical_data: A pandas DataFrame with historical bars.
                                Expected columns: 'time', 'open', 'high', 'low', 'close'.
        """
        self.mm = market_maker
        self.data = historical_data.sort_values('time').reset_index(drop=True)
        self.results = []  # to store simulation results per bar

    def simulate_fill(self, order: LimitOrder, bar: pd.Series) -> bool:
        """
        Simplified fill simulation:
          - For a BUY (bid) order, assume fill if the bar's low is less than or equal to the order price.
          - For a SELL (ask) order, assume fill if the bar's high is greater than or equal to the order price.
        You could add randomness or partial fills for more realism.
        """
        if order.action == 'BUY' and bar['low'] <= order.lmtPrice:
            return True
        elif order.action == 'SELL' and bar['high'] >= order.lmtPrice:
            return True
        return False

    def run(self):
        """
        Run the backtest over all bars in the historical data.
        At each bar, we:
          - Append the bar to the market maker's history (for ATR calculations).
          - Compute an effective mid price (here, we use the bar's close price).
          - Have the market maker compute bid and ask quotes.
          - Simulate fills based on the bar's high/low.
          - Update the risk manager if fills occur.
          - Record the outcome.
        """
        # Reset any history in the market maker
        self.mm.bars = []
        # We'll also record a simple log per bar
        for idx, bar in self.data.iterrows():
            # Append current bar data to the market maker's history
            # Here we assume each 'bar' is a pd.Series with 'high', 'low', 'close'
            self.mm.bars.append(bar)
            self.mm.update_ATR()

            # For simulation, use the bar's close as a proxy for the mid price.
            mid = bar['close']
            # Incorporate risk inventory skew
            inv_offset = self.mm.risk_manager.inventory_skew(mid)
            effective_mid = mid + inv_offset

            # Compute dynamic spread (using your function that factors ATR and directional bias)
            final_spread = self.mm.dynamic_spread()
            bid_price = round(effective_mid - final_spread / 2, 2)
            ask_price = round(effective_mid + final_spread / 2, 2)

            # Create dummy orders for bid and ask
            qty = 100  # for backtest simplicity
            bid_order = LimitOrder('BUY', qty, bid_price)
            ask_order = LimitOrder('SELL', qty, ask_price)

            # Simulate fills based on the bar's price range
            bid_filled = self.simulate_fill(bid_order, bar)
            ask_filled = self.simulate_fill(ask_order, bar)

            # If an order is filled, update risk manager
            if bid_filled:
                # Create a dummy fill event
                fill_event = type("Fill", (), {})()
                fill_event.order = bid_order
                fill_event.filled = qty
                fill_event.price = bid_price
                self.mm.risk_manager.update_after_fill(fill_event)
            if ask_filled:
                fill_event = type("Fill", (), {})()
                fill_event.order = ask_order
                fill_event.filled = qty
                fill_event.price = ask_price
                self.mm.risk_manager.update_after_fill(fill_event)

            # Record bar results
            self.results.append({
                'time': bar['time'],
                'bid_price': bid_price,
                'ask_price': ask_price,
                'bid_filled': bid_filled,
                'ask_filled': ask_filled,
                'current_inventory': self.mm.risk_manager.current_position,
                'ATR': self.mm.atr_value,
                'spread': final_spread
            })

        return pd.DataFrame(self.results)


# ---------------------------
# Example usage of the backtesting infrastructure:
# ---------------------------

if __name__ == '__main__':
    # For backtesting we won't connect to IB.
    # Instead, we simulate a "dummy" IB instance that our market maker needs.
    # In a full implementation, you might refactor your code to decouple live data.
    ib_dummy = IB()

    # Define a dummy contract (for backtesting, the details don't matter too much)
    contract = Stock('NBIS', 'SMART', 'USD')

    # Create a RiskManager instance
    rm = RiskManager(max_position=500,
                     daily_loss_limit=1000.0,
                     inventory_skew_factor=0.02)

    # Create the VolatilityMarketMaker with a directional bias (e.g., bullish bias 0.3)
    mm = VolatilityMarketMaker(
        ib=ib_dummy,
        contract=contract,
        risk_manager=rm,
        directional_bias=0.3,
        base_spread=0.10,
        min_spread=0.05,
        max_spread=0.50,
        atr_period=14,
        atr_multiplier=0.5
    )

    # Load historical data from CSV (or create dummy data)
    # For example, we expect a CSV with columns: time, open, high, low, close
    # Here we create some dummy data for demonstration:
    periods = 2000
    dates = pd.date_range(start='2023-01-01 09:30', periods=periods, freq='5min')
    dummy_data = pd.DataFrame({
        'time': dates,
        'open': np.random.uniform(50, 60, size=periods),
        'high': np.random.uniform(60, 62, size=periods),
        'low': np.random.uniform(48, 50, size=periods),
        'close': np.random.uniform(50, 60, size=periods)
    })

    # Create the backtest engine and run the simulation
    backtester = BacktestEngine(market_maker=mm, historical_data=dummy_data)
    results_df = backtester.run()

    # Display the backtest results
    print(results_df.head())

    # You can further analyze the results, for example plotting inventory over time,
    # computing PnL (if you add PnL calculations), or other performance metrics.
