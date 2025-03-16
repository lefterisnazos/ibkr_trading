import math
import time
import numpy as np
from ib_insync import IB, Stock, LimitOrder, util

class RiskManager:
    """
    Handles inventory limits, daily PnL limits, and position-based skew.
    """
    def __init__(self,
                 max_position=1000,
                 daily_loss_limit=500.0,
                 inventory_skew_factor=0.01):
        """
        :param max_position: Maximum absolute position size allowed.
        :param daily_loss_limit: Maximum daily realized loss before stopping.
        :param inventory_skew_factor: How strongly to skew quotes based on inventory.
        """
        self.max_position = max_position
        self.daily_loss_limit = daily_loss_limit
        self.inventory_skew_factor = inventory_skew_factor

        # Track position and PnL
        self.current_position = 0
        self.realized_pnl = 0.0

    def update_after_fill(self, fill_event):
        """
        Update current_position and realized_pnl based on fill info.
        This requires you track fill prices and average cost, or have a separate PnL calc.
        For simplicity, we assume you know the fill PnL or track it externally.
        """
        fill = fill_event
        action = fill.order.action  # 'BUY' or 'SELL'
        qty_filled = fill.filled
        fill_price = fill.price  # average fill price

        # Update position
        if action == 'BUY':
            self.current_position += qty_filled
        elif action == 'SELL':
            self.current_position -= qty_filled

        # (Optional) update realized PnL if you close out part of your position, etc.
        # This can get more complex if you track average cost. For a simple approach:
        # self.realized_pnl += fill_pnl
        # For demonstration, let's do nothing or a placeholder:
        # self.realized_pnl += 0  # you would compute the actual fill-based PnL here

    def can_trade(self):
        """
        Check if we're still within risk limits. Return True if we can continue,
        False if we must stop/pause trading.
        """
        # Check daily loss limit
        if self.realized_pnl <= -abs(self.daily_loss_limit):
            return False
        return True

    def within_inventory_limits(self, action, quantity):
        """
        Check if adding this new trade (action, quantity) would exceed position limits.
        Return True if within limits, False if it breaks them.
        """
        hypothetical_pos = self.current_position
        if action == 'BUY':
            hypothetical_pos += quantity
        else:
            hypothetical_pos -= quantity
        return abs(hypothetical_pos) <= self.max_position

    def inventory_skew(self, mid_price):
        """
        Compute a price offset (in dollars) based on current position.
        If long, we shift quotes up to encourage selling. If short, shift quotes down to encourage covering.
        :return: float offset in price units.
        """
        # The fraction of how 'full' our inventory is, in [-1, 1]
        inv_fraction = self.current_position / float(self.max_position)
        # The offset grows with inventory. Positive offset = shift quotes upward if we're long.
        offset = inv_fraction * self.inventory_skew_factor * mid_price
        return offset

class VolatilityMarketMaker:
    """
    A volatility-based market maker with optional directional bias and risk management.
    """
    def __init__(self,
                 ib: IB,
                 contract: Stock,
                 risk_manager: RiskManager,
                 directional_bias=0.0,
                 base_spread=0.10,
                 min_spread=0.05,
                 max_spread=0.50,
                 atr_period=14,
                 atr_multiplier=0.5):
        """
        :param ib: IB instance (ib_insync connection).
        :param contract: The Stock contract to trade.
        :param risk_manager: Instance of RiskManager for positions & PnL.
        :param directional_bias: +ve means prefer long, -ve prefer short, 0 = neutral.
        :param base_spread: Base spread in dollars (before volatility scaling).
        :param min_spread: Minimum absolute spread allowed.
        :param max_spread: Maximum absolute spread allowed.
        :param atr_period: Number of bars for ATR calculation.
        :param atr_multiplier: Factor to scale ATR into a spread.
        """
        self.ib = ib
        self.contract = contract
        self.risk_manager = risk_manager

        self.directional_bias = directional_bias
        self.base_spread = base_spread
        self.min_spread = min_spread
        self.max_spread = max_spread

        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier

        # Keep track of existing orders so we can cancel/modify
        self.current_bid_order = None
        self.current_ask_order = None

        # We will store bar data for ATR
        self.bars = []
        self.atr_value = None

    def compute_ATR(self, bars, period):
        """
        Compute the Average True Range given a list of bars (each bar has high, low, close).
        """
        tr_values = []
        for i in range(1, len(bars)):
            high = bars[i].high
            low = bars[i].low
            prev_close = bars[i-1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_values.append(tr)
        if len(tr_values) < period:
            return None
        # Last 'period' TR values
        return sum(tr_values[-period:]) / period

    def update_ATR(self):
        """
        Refresh the ATR value from self.bars.
        """
        self.atr_value = self.compute_ATR(self.bars, self.atr_period)

    def dynamic_spread(self):
        """
        Calculate the final dynamic spread using ATR, base spread, directional bias,
        and risk manager's inventory skew.
        """
        # Start with base spread
        spread = self.base_spread

        # If we have a valid ATR, scale by atr_multiplier
        if self.atr_value is not None:
            spread += self.atr_multiplier * self.atr_value

        # Apply min/max clamps
        spread = max(spread, self.min_spread)
        spread = min(spread, self.max_spread)

        # Now incorporate directional bias:
        # A positive directional bias => narrower spread on the bid side (more aggressive buying)
        # and slightly wider on the ask side (less aggressive selling).
        # Conversely, negative bias => narrower spread on the ask side, etc.
        # For simplicity, let's just reduce the final spread if bias > 0,
        # or widen it if bias < 0. This is one approach; you can design more sophisticated logic.
        if self.directional_bias != 0:
            # Example: reduce spread by up to 20% if bias is +1, or increase if bias is -1
            # (You can customize this scaling function as you like.)
            spread *= (1 - 0.2 * self.directional_bias)
            print(f'{self.contract.symbol}: directional adjustment by {(1 - 0.2 * self.directional_bias)}')

        return spread

    def place_quotes(self):
        """
        Place or update our bid/ask limit orders according to the dynamic spread and risk checks.
        """
        ticker = self.ib.reqMktData(self.contract, '', False, False)
        if ticker.bid is None or ticker.ask is None:
            return  # not enough data yet
        mid = (ticker.bid + ticker.ask) / 2.0

        # Get a skew from risk manager based on current inventory
        inv_offset = self.risk_manager.inventory_skew(mid)

        # Adjust the mid price by inventory offset
        # If we are heavily long, offset > 0 => shift mid up => we place a higher ask and a higher bid (less aggressive on buy).
        # If we are heavily short, offset < 0 => shift mid down => more aggressive on buy, less on sell.
        effective_mid = mid + inv_offset

        # Calculate final dynamic spread
        final_spread = self.dynamic_spread(effective_mid)

        bid_px = round(effective_mid - final_spread / 2, 2)
        ask_px = round(effective_mid + final_spread / 2, 2)

        # Decide the quantity to place (for demonstration, fixed size).
        # You could also adapt size based on volatility or inventory.
        qty = 100

        # Risk check if we can place buy or sell
        can_buy = self.risk_manager.within_inventory_limits('BUY', qty)
        can_sell = self.risk_manager.within_inventory_limits('SELL', qty)

        # Cancel existing orders if they're too far off from new price or if we can't trade
        if self.current_bid_order:
            old_bid = self.current_bid_order.order.lmtPrice
            if abs(old_bid - bid_px) > 0.01 or not can_buy:
                self.ib.cancelOrder(self.current_bid_order.order)
                self.current_bid_order = None

        if self.current_ask_order:
            old_ask = self.current_ask_order.order.lmtPrice
            if abs(old_ask - ask_px) > 0.01 or not can_sell:
                self.ib.cancelOrder(self.current_ask_order.order)
                self.current_ask_order = None

        # Place new limit orders if none exist and risk is okay
        if can_buy and not self.current_bid_order:
            bid_order = LimitOrder('BUY', qty, bid_px)
            self.current_bid_order = self.ib.placeOrder(self.contract, bid_order)

        if can_sell and not self.current_ask_order:
            ask_order = LimitOrder('SELL', qty, ask_px)
            self.current_ask_order = self.ib.placeOrder(self.contract, ask_order)

    def on_fill(self, trade):
        """
        Callback to handle fill events and update the risk manager.
        `trade` is an ib_insync Trade object that has execution details.
        """
        fill = trade.fills[-1]  # the most recent fill
        self.risk_manager.update_after_fill(fill)

    def run(self, duration_seconds=300):
        """
        Main loop for demonstration. Subscribes to bar data, updates ATR, places quotes, checks risk.
        Exits after duration_seconds or if risk is breached.
        """
        # Get some historical data to seed ATR
        hist_bars = self.ib.reqHistoricalData(
            self.contract,
            endDateTime='',
            durationStr='2 D',
            barSizeSetting='5 mins',
            whatToShow='TRADES',
            useRTH=True
        )
        self.bars = hist_bars
        self.update_ATR()

        # Real-time bar subscription for continuing ATR updates
        # This is optional, or you could update ATR from tick data.
        # For demonstration, we'll request real-time bars if your IB account supports it.
        self.ib.reqRealTimeBars(self.contract, 5, 'TRADES', False)

        # Listen for fills
        self.ib.executionsEvent += self.on_fill

        start_time = time.time()
        while time.time() - start_time < duration_seconds:
            self.ib.waitOnUpdate(timeout=1)

            # Check risk manager - if we can't trade, break
            if not self.risk_manager.can_trade():
                print("Risk limits breached. Stopping market making.")
                break

            # Periodically update ATR (e.g., once per bar or every few seconds)
            # For a quick example, let's just do it every iteration if new bar is formed
            # A more robust approach: track bar timestamps, update at bar close, etc.
            new_bars = self.ib.reqHistoricalData(
                self.contract,
                endDateTime='',
                durationStr='30 M',
                barSizeSetting='5 mins',
                whatToShow='TRADES',
                useRTH=True
            )
            if new_bars:
                self.bars = new_bars
                self.update_ATR()

            # Place or update quotes
            self.place_quotes()

        # Cancel any remaining orders if we exit
        if self.current_bid_order:
            self.ib.cancelOrder(self.current_bid_order.order)
        if self.current_ask_order:
            self.ib.cancelOrder(self.current_ask_order.order)
        print("Market making stopped.")


if __name__ == '__main__':
    ib = IB()
    ib.connect('127.0.0.1', 7497, clientId=101)

    # Define the contract to trade
    contract = Stock('NBIS', 'SMART', 'USD')
    ib.qualifyContracts(contract)

    # Create a RiskManager
    rm = RiskManager(max_position=500,  # e.g., 500 shares limit
                     daily_loss_limit=1000.0,  # stop if we lose 1000
                     inventory_skew_factor=0.02)  # 2% skew factor

    # Create the MarketMaker with a slight bullish bias
    # e.g., directional_bias = 0.3 means "lean 30% towards long"
    mm = VolatilityMarketMaker(
        ib=ib,
        contract=contract,
        risk_manager=rm,
        directional_bias=0.3,   # positive = bullish
        base_spread=0.10,
        min_spread=0.05,
        max_spread=0.50,
        atr_period=14,
        atr_multiplier=0.5
    )

    # Run the strategy for a set duration (e.g., 5 minutes)
    mm.run(duration_seconds=300)
