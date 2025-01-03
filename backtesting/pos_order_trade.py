
# Order not used current for the backtester. Only Position & Trade are needed
class Order:
    """
    Represents an Order to buy or sell a contract at a specific (or market) price.
    For backtesting, the 'execution' is immediate once we decide to fill it.
    """
    def __init__(self, order_id, contract, price, volume, side, timestamp, comment=""):
        self.id = order_id
        self.contract = contract
        self.price = price
        self.volume = volume
        self.side = side  # "B" (buy) or "S" (sell)
        self.timestamp = timestamp
        self.comment = comment

    def __repr__(self):
        return f"Order(id={self.id}, side={self.side}, vol={self.volume}, px={self.price}, {self.comment})"


class Trade:
    """
    A completed transaction that affects a position, logging realized PnL (if any).
    """
    def __init__(self, contract, price, volume, side, timestamp, comment=""):
        self.contract = contract
        self.price = price
        self.volume = volume
        self.side = side  # "B" or "S"
        self.timestamp = timestamp
        self.comment = comment
        self.realized_pnl = 0
        self.realized_return = 0

    def __repr__(self):
        return (f"Trade({self.contract}, {self.side}, vol={self.volume}, "
                f"px={round(self.price, 2)}, PnL={round(self.realized_pnl, 2)}, Return={round(self.realized_return, 4)})")

    def __str__(self):
        return (f"Trade({self.contract}, {self.side}, vol={self.volume}, "
                f"px={round(self.price, 2)}, PnL={round(self.realized_pnl, 2)}, Return={round(self.realized_return, 4)})")

    def __hash__(self):
        return hash((self.contract, self.side, self.volume, self.price, self.timestamp)).__hash__()

class Position:
    """
    An open position that tracks average entry price, side, and total volume.
    """
    def __init__(self, contract, price, volume, side, timestamp):
        self.contract = contract
        self.avg_price = price
        self.volume = volume
        self.side = side  # "B" for long, "S" for short
        self.open_timestamp = timestamp
        self.last_update = timestamp

    def add(self, trade: Trade):
        """
        Increase the position's volume (same side), recalc avg price.
        """
        if self.side != trade.side:
            raise ValueError("Cannot add to position with a trade of opposite side.")
        new_vol = self.volume + trade.volume
        self.avg_price = ((self.avg_price * self.volume) + (trade.price * trade.volume)) / new_vol
        self.volume = new_vol
        self.last_update = trade.timestamp

    def reduce(self, trade: Trade):
        """
        Close or partially reduce a position using an opposite-side trade.
        """
        if self.side == trade.side:
            raise ValueError("Cannot reduce a position with a trade of the same side.")
        # Realized PnL depends on side
        if self.side == "B":  # long
            realized_pnl = (trade.price - self.avg_price) * min(self.volume, trade.volume)
            realized_return = realized_pnl / (self.avg_price * min(self.volume, trade.volume))
        else:  # short
            realized_pnl = (self.avg_price - trade.price) * min(self.volume, trade.volume)
            realized_return = realized_pnl / (self.avg_price * min(self.volume, trade.volume))

        # If trade volume > position volume => flipping side
        if trade.volume > self.volume:
            # leftover volume changes side & avg_price
            leftover_vol = trade.volume - self.volume
            self.side = trade.side
            self.avg_price = trade.price
            self.volume = leftover_vol
        else:
            # partial or full close
            self.volume -= trade.volume

        self.last_update = trade.timestamp
        trade.realized_pnl = realized_pnl
        trade.realized_return = realized_return

    def is_open(self):
        return self.volume > 0