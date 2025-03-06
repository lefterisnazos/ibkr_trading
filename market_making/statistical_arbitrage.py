from ib_insync import IB, Stock, LimitOrder
import numpy as np

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=2)

# Define the pair contracts
stock1 = Stock('AAA', 'SMART', 'USD')
stock2 = Stock('BBB', 'SMART', 'USD')
ib.qualifyContracts(stock1, stock2)

# Historical data to estimate initial hedge ratio
hist1 = ib.reqHistoricalData(stock1, endDateTime='', durationStr='30 D',barSizeSetting='1 day', whatToShow='TRADES', useRTH=True)
hist2 = ib.reqHistoricalData(stock2, endDateTime='', durationStr='30 D',barSizeSetting='1 day', whatToShow='TRADES', useRTH=True)

prices1 = [bar.close for bar in hist1]
prices2 = [bar.close for bar in hist2]

# Simple linear regression for initial beta: price2 = beta * price1 + c
beta_init = np.cov(prices1, prices2)[0,1] / np.var(prices1)  # slope estimate
hedge_ratio = beta_init
intercept = np.mean(prices2) - hedge_ratio * np.mean(prices1)  # for info, might use or assume 0 intercept for simplicity

# Kalman filter parameters for hedge ratio updating
beta = hedge_ratio
P = 1.0  # initial covariance of beta estimate
R = 0.001  # measurement noise (tune as needed)
Q = 0.0001  # process noise (how much we allow beta to drift each step)

# Subscribe to real-time market data
tkr1 = ib.reqMktData(stock1, '', False, False)
tkr2 = ib.reqMktData(stock2, '', False, False)

# Variables for spread mean and std estimation
spread_window = []  # rolling window of spread for std dev
window_size = 100

# Active orders trackers
order_leg1 = None
order_leg2 = None

# Trading thresholds (in terms of z-score)
entry_thresh = 2.0
exit_thresh = 0.5

while True:
    ib.waitOnUpdate()  # wait for tick update
    if tkr1.last is None or tkr2.last is None:
        continue  # wait until both have data
    price1 = tkr1.last
    price2 = tkr2.last

    # Kalman Filter update for hedge ratio (beta)
    # Predict step
    beta = beta  # (beta is assumed random walk, no change)
    P = P + Q
    # Measurement update step
    # measurement: we treat price2 as beta * price1 + noise
    # innovation (residual) = actual price2 - predicted price2
    pred_price2 = beta * price1
    resid = price2 - pred_price2
    # Kalman gain
    K = P * price1 / (price1*price1 * P + R)
    # Update beta with innovation
    beta = beta + K * resid
    # Update covariance
    P = (1 - K * price1) * P

    hedge_ratio = beta  # updated hedge ratio

    # Compute current spread and z-score
    spread = price2 - hedge_ratio * price1
    spread_window.append(spread)
    if len(spread_window) > window_size:
        spread_window.pop(0)
    spread_mean = np.mean(spread_window) if spread_window else 0
    spread_std = np.std(spread_window) if spread_window else 1e-6
    z_score = 0 if spread_std == 0 else (spread - spread_mean) / spread_std

    # Check for trade signals based on z-score
    if z_score > entry_thresh:
        # Spread too high: Stock2 overpriced vs Stock1
        # Place SELL on stock2 and BUY on stock1 if not already in a trade
        if not order_leg1 and not order_leg2:
            qty2 = 100  # units to trade, e.g. 100 shares of stock2
            qty1 = int(qty2 * hedge_ratio)  # shares of stock1 based on hedge ratio
            sell_price2 = price2 * 0.995  # a bit below current price to get hit (provide liquidity)
            buy_price1 = price1 * 1.005   # a bit above current price to get hit on the buy
            order_leg2 = ib.placeOrder(stock2, LimitOrder('SELL', qty2, round(sell_price2, 2)))
            order_leg1 = ib.placeOrder(stock1, LimitOrder('BUY', qty1, round(buy_price1, 2)))
            # Note: In practice, use bracket or ensure one leg won't execute without the other.
    elif z_score < -entry_thresh:
        # Spread too low: Stock2 underpriced vs Stock1
        if not order_leg1 and not order_leg2:
            qty1 = 100  # trade 100 shares of stock1 (since now stock1 is overpriced relative)
            qty2 = int(qty1 * hedge_ratio)  # shares of stock2 based on hedge
            sell_price1 = price1 * 0.995
            buy_price2 = price2 * 1.005
            order_leg1 = ib.placeOrder(stock1, LimitOrder('SELL', qty1, round(sell_price1, 2)))
            order_leg2 = ib.placeOrder(stock2, LimitOrder('BUY', qty2, round(buy_price2, 2)))
    # Exit logic: if we have an open pair trade and z_score returns near 0, exit the positions
    if order_leg1 and order_leg2:
        if abs(z_score) < exit_thresh:
            # Close positions by taking opposite trades (or use stored fill info to know position size)
            # (Here we assume orders fully filled; in practice track fills)
            filled_qty1 = order_leg1.order.totalQuantity
            filled_qty2 = order_leg2.order.totalQuantity
            ib.placeOrder(stock1, LimitOrder('BUY' if order_leg1.order.action == 'SELL' else 'SELL',
                                             filled_qty1, tkr1.last))
            ib.placeOrder(stock2, LimitOrder('BUY' if order_leg2.order.action == 'SELL' else 'SELL',
                                             filled_qty2, tkr2.last))
            order_leg1 = None
            order_leg2 = None
            spread_window.clear()  # reset spread window after exiting a trade cycle
