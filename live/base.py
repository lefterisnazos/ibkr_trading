from ib_insync import IB, Stock, Trade as IBTrade, Fill
from pos_order_trade_live import *
from backtesting.strategies.base import BaseStrategy
from live.ib_client_live import IBClient


class BaseStrategyLive:
    def __init__(self, client_id=25):
        super().__init__(client_id=client_id, live_mode=True)
        # Subscribe to trade updates
        self.ib_client = IBClient(port=7497, client_id=client_id)
        self.ib_client.ib.tradeUpdateEvent += self.on_trade_update
        self.connect_to_ib()

        self.position = {}
        self.trades = {}
        self.pnl = {}

    @self.ib_client.ib.on('tradeUpdate')
    def onTradeUpdate(self, trade: IBTrade):
        # Check trade.status, trade.fills, partial fills, etc.
        # Convert each fill to your local Trade object & call add_position() or reduce_position().
        # E.g.:
        if not trade.fills:
            return

        for fill in trade.fills:
            ib_side = fill.execution.side  # "BOT" or "SLD"
            local_side = "B" if ib_side == "BOT" else "S"

            ticker = trade.contract.symbol
            fill_price = fill.execution.avgPrice
            fill_qty = fill.execution.shares
            fill_time = fill.execution.time

            local_trade = Trade(contract=ticker, price=fill_price, volume=fill_qty, side=local_side, timestamp=fill_time,
                comment=f"Live fill (execId={fill.execution.execId})")

            # If side matches existing position side => add
            if local_side == "B":
                if self.position[ticker] is None or self.position[ticker].side == "B":
                    self.add_position(local_trade, ticker)
                else:
                    self.reduce_position(local_trade, ticker)
            else:  # local_side == "S"
                if self.position[ticker] is None or self.position[ticker].side == "S":
                    self.add_position(local_trade, ticker)
                else:
                    self.reduce_position(local_trade, ticker)


    def on_trade_update(self, trade: IBTrade):
        """
        Called automatically whenever a trade is updated with a partial fill, fill, etc.
        Use this to update our position objects.
        """
        if not trade.fills:
            return

        for fill in trade.fills:
            side = "B" if fill.execution.side == "BOT" else "S"
            fill_price = fill.execution.avgPrice
            fill_qty = fill.execution.shares
            fill_time = fill.execution.time
            ticker = trade.contract.symbol

            # Convert ib_insync fill to your local “Trade” object
            local_trade = Trade(
                contract=ticker,
                price=fill_price,
                volume=fill_qty,
                side=side,
                timestamp=fill_time,
                comment=f"Live fill (execId={fill.execution.execId})"
            )

            if side == "B" and (self.position[ticker] is None or self.position[ticker].side == "B"):
                self.add_position(local_trade, ticker)
            elif side == "S" and (self.position[ticker] is None or self.position[ticker].side == "S"):
                self.add_position(local_trade, ticker)
            else:
                self.reduce_position(local_trade, ticker)

    def connect_to_ib(self):
        """ Connect to Interactive Brokers TWS or IB Gateway. """
        self.ib_client.connect()

    def disconnect_from_ib(self):
        if self.live_mode:
            self.ib_client.disconnect()

    def reduce_position(self, trade: Trade, ticker: str = None):
        self.position[ticker].reduce(trade)
        if self.position[ticker].volume == 0:
            self.position[ticker] = None

        self.pnl[ticker].append(trade)
        self.trades[ticker].append(trade)
        print(trade)

    def add_position(self, trade: Trade, ticker: str = None):
        if self.position[ticker] is None:
            self.position[ticker] = Position(contract=trade.contract, price=trade.price, volume=trade.volume, side=trade.side, timestamp=trade.timestamp)
        else:
            self.position[ticker].add(trade)

        self.trades[ticker].append(trade)
        print(trade)