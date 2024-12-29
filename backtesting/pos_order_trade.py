# risk_management.py

import datetime as dt

class Order:
    """
    Represents an Order to buy or sell a contract at a specific (or market) price.
    """
    def __init__(self, order_id, contract, price, volume, side, timestamp, comment=""):
        """
        :param price: float or "M" for market
        :param volume: int
        :param side: "B" (buy) or "S" (sell)
        :param timestamp: datetime
        :param comment: additional comment
        """
        self.id = order_id
        self.contract = contract
        self.price = price
        self.volume = volume
        self.side = side
        self.timestamp = timestamp
        self.comment = comment


class Trade:
    """
    Represents a completed transaction in the market.
    Keeps track of realized PnL for this transaction.
    """
    def __init__(self, contract, price, volume, side, timestamp, comment=""):
        self.contract = contract
        self.price = price
        self.volume = volume
        self.side = side
        self.timestamp = timestamp
        self.comment = comment
        self.realized_pnl = 0

    def __repr__(self):
        return (f"({str(self.timestamp)}) - {self.contract}: {self.side}|{str(self.volume)}@"
                f"{str(round(self.price, 2))} (Realized PnL: {str(round(self.realized_pnl, 2))}) {self.comment}")

    def __str__(self):
        return (f"({str(self.timestamp)}) - {self.contract}: {self.side}|{str(self.volume)}@"
                f"{str(round(self.price, 2))} (Realized PnL: {str(round(self.realized_pnl, 2))}) {self.comment}")


class Position:
    """
    Signifies an active stake in a particular product.
    Tracks average entry price, total volume, and side (long/short).
    """
    def __init__(self, contract, price, volume, side, timestamp):
        self.contract = contract
        self.price = price
        self.volume = volume
        self.side = side  # "B" or "S"
        self.open_timestamp = timestamp
        self.last_update = timestamp

    def add(self, trade: Trade):
        """
        Increase the position’s volume when we add trades going in the same direction.
        Recalculate the average price accordingly.
        """
        if self.contract != trade.contract:
            raise ValueError("Cannot add to the position: different product.")

        if self.side != trade.side:
            raise ValueError("Cannot add to the position: trade side differs from the open position.")

        new_total_volume = self.volume + trade.volume
        self.price = (self.price * self.volume + trade.price * trade.volume) / new_total_volume
        self.volume = new_total_volume
        self.last_update = trade.timestamp

    def reduce(self, trade: Trade):
        """
        Reduce or close the position with an opposite-side trade.
        Compute realized PnL for that trade.
        """
        if self.contract != trade.contract:
            raise ValueError("Cannot reduce the position: different product.")
        if self.side == trade.side:
            raise ValueError("Cannot reduce the position: same side trade.")

        if self.side == "B":  # long
            realized_pnl = (trade.price - self.price) * min(trade.volume, self.volume)
        else:  # short
            realized_pnl = (self.price - trade.price) * min(trade.volume, self.volume)

        # If trade volume > position volume, the new position might flip
        # from B to S or S to B. For simplicity, we assume it flips.
        if trade.volume > self.volume:
            self.price = trade.price
            self.side = trade.side

        self.volume = abs(self.volume - trade.volume)
        self.last_update = trade.timestamp
        trade.realized_pnl = realized_pnl

    def close(self, close_price, current_timestamp):
        """
        Closes the position at the given close_price, returning a market Order
        in the opposite side to flatten the position.
        """
        if self.volume == 0:
            return None  # no position to close

        close_side = "B" if self.side == "S" else "S"
        close_order = Order(
            order_id='close_' + self.contract,
            contract=self.contract,
            price='M',  # Market price
            volume=self.volume,
            side=close_side,
            timestamp=current_timestamp,
            comment="Closing position"
        )
        return close_order
