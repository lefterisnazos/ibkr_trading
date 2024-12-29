from pos_order_trade import Position


class Signal:

    def check(self, position: Position, data):
        raise NotImplementedError




class TakeProfit(Signal):

    def __init__(self, take_profit=0.1):
        self.take_profit = take_profit

    def check(self, position: Position, data):
        if position.side == 'B' and data[data['product'] == position.product]['best_bid_price'][0] is None:
            return False
        elif position.side == 'S' and data[data['product'] == position.product]['best_ask_price'][0] is None:
            return False
        return (position.side == 'B' and data[data['product'] == position.product]['best_bid_price'][0] >= position.price * (1 + self.take_profit)) or \
               (position.side == 'S' and data[data['product'] == position.product]['best_ask_price'][0] <= position.price * (1 - self.take_profit))


class StopLoss(Signal):

    def __init__(self, stop_loss=0.2):
        self.stop_loss = stop_loss

    def check(self, position: Position, data):
        if position.side == 'B' and data[data['product'] == position.product]['best_bid_price'][0] is None:
            return False
        elif position.side == 'S' and data[data['product'] == position.product]['best_ask_price'][0] is None:
            return False
        return (position.side == 'B' and data[data['product'] == position.product]['best_bid_price'][0] <= position.price * (1 - self.stop_loss)) or \
               (position.side == 'S' and data[data['product'] == position.product]['best_ask_price'][0] >= position.price * (1 + self.stop_loss))
