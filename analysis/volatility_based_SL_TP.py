import datetime
import time
from ib_insync import IB, Stock, util

'''
1) Reads all open orders from IB.
2) Groups them into “bracket” orders (i.e. groups that include both a TakeProfit order and a StopLoss order).
3) For each bracket group it:
   * Uses the parent order’s placement time as a “baseline” reference.
   * Computes a volatility metric (here using a simple ATR calculation) both at baseline and in the current market.
   * Computes a ratio of current ATR to baseline ATR.
   * Then adjusts the stop-loss and take-profit prices by widening 
      (if volatility increased) or tightening (if volatility decreased) the original distance from the entry.
'''

util.startLoop()  # only needed if running in an interactive environment

# === Configuration Parameters ===
ATR_PERIOD = 14  # number of bars for ATR calculation
VOL_DURATION = '2 D'  # historical data duration (2 days in this example)
BAR_SIZE = '1 hour'  # bar size for ATR calculation

# === Connect to IB ===
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=123)


def calculate_ATR(contract, end_datetime, period=ATR_PERIOD):
    """
    Calculate the Average True Range (ATR) for a given contract.

    Parameters:
      contract     - IB contract object (e.g. a Stock)
      end_datetime - A string in IB format ('YYYYMMDD HH:MM:SS') indicating the end of the data period.
                     Passing an empty string ('') will return data up to the current time.
      period       - The number of bars to use for the ATR calculation.

    Returns:
      The ATR value (float) or None if insufficient data.
    """
    bars = ib.reqHistoricalData(
        contract,
        endDateTime=end_datetime,
        durationStr=VOL_DURATION,
        barSizeSetting=BAR_SIZE,
        whatToShow='MIDPOINT',
        useRTH=True
    )
    if len(bars) < period + 1:
        return None
    tr_list = []
    for i in range(1, period + 1):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i - 1].close
        true_range = max(high, prev_close) - min(low, prev_close)
        tr_list.append(true_range)
    atr = sum(tr_list) / len(tr_list)
    return atr


def groupBracketOrders(open_orders):
    """
    Group open orders into bracket groups using their parentId.

    Each bracket group is assumed to contain a parent order plus its child orders.
    We assume that child orders include one Stop (orderType 'STP') and one TakeProfit (orderType 'LMT').
    """
    groups = {}
    for order in open_orders:
        # Use the parentId if available; otherwise, use the orderId as the group key.
        key = order.parentId if order.parentId else order.orderId
        if key not in groups:
            groups[key] = []
        groups[key].append(order)
    return groups


# === Main Script: Adjust orders based on changing volatility ===

# 1. Retrieve all open orders.
open_orders = ib.openOrders()
if not open_orders:
    print("No open orders found.")

# 2. Group orders into bracket groups.
order_groups = groupBracketOrders(open_orders)

# 3. Iterate over each group that contains both a StopLoss and a TakeProfit.
for group_id, orders in order_groups.items():
    tp_order = None
    sl_order = None
    parent_order = None
    for order in orders:
        if order.orderType == 'LMT':
            tp_order = order
        elif order.orderType == 'STP':
            sl_order = order
        else:
            parent_order = order  # assume parent entry order is not LMT/STP

    # Proceed only if both take profit and stop loss orders exist.
    if not tp_order or not sl_order:
        continue

    # Assume the contract is the same for all orders in the group.
    contract = orders[0].contract

    # --- Use parent's order attributes as baseline reference ---
    # It is assumed that when the parent order was executed, you stored:
    #   parent_order.placedTime -> a datetime object marking when the order was placed
    #   parent_order.entryPrice -> the fill price (entry price)
    if parent_order is None:
        print(f"Group {group_id}: No parent order found; skipping adjustment.")
        continue
    if not hasattr(parent_order, 'placedTime') or not hasattr(parent_order, 'entryPrice'):
        print(f"Group {group_id}: Parent order missing placedTime or entryPrice; skipping adjustment.")
        continue

    entry_price = parent_order.entryPrice
    placed_time = parent_order.placedTime  # expected to be a datetime.datetime object

    # Convert placed_time to IB's historical data format (YYYYMMDD HH:MM:SS)
    baseline_end = placed_time.strftime('%Y%m%d %H:%M:%S')

    # --- Calculate baseline and current volatility using ATR ---
    baseline_atr = calculate_ATR(contract, baseline_end, ATR_PERIOD)
    current_atr = calculate_ATR(contract, '', ATR_PERIOD)  # current ATR up to now
    if baseline_atr is None or current_atr is None:
        print(f"{contract.symbol}: Insufficient historical data for ATR calculation.")
        continue

    # Compute the ratio of current volatility to the volatility at order placement.
    ratio = current_atr / baseline_atr if baseline_atr != 0 else 1.0
    print(
        f"{contract.symbol} - Group {group_id}: Baseline ATR = {baseline_atr:.2f}, Current ATR = {current_atr:.2f}, Ratio = {ratio:.2f}")

    # --- Adjust StopLoss and TakeProfit levels based on the volatility ratio ---
    # For a long position, we assume:
    #   StopLoss is below entry: original_sl_distance = entry_price - sl_order.stopPrice
    #   TakeProfit is above entry: original_tp_distance = tp_order.lmtPrice - entry_price
    # For a short position, these distances are reversed.
    is_long = entry_price < tp_order.lmtPrice  # simple assumption: if TP > entry then long

    if is_long:
        original_sl_distance = entry_price - sl_order.stopPrice
        original_tp_distance = tp_order.lmtPrice - entry_price
        new_sl_distance = original_sl_distance * ratio
        new_tp_distance = original_tp_distance * ratio
        new_sl_price = entry_price - new_sl_distance
        new_tp_price = entry_price + new_tp_distance
    else:
        original_sl_distance = sl_order.stopPrice - entry_price
        original_tp_distance = entry_price - tp_order.lmtPrice
        new_sl_distance = original_sl_distance * ratio
        new_tp_distance = original_tp_distance * ratio
        new_sl_price = entry_price + new_sl_distance
        new_tp_price = entry_price - new_tp_distance

    # Print new boundaries for verification.
    print(
        f"Updating {contract.symbol}: New StopLoss = {round(new_sl_price, 2)}, New TakeProfit = {round(new_tp_price, 2)}")

    # --- Update orders with new boundaries ---
    # For Stop orders, update the stopPrice attribute.
    sl_order.stopPrice = round(new_sl_price, 2)
    # For Limit orders (TakeProfit), update the lmtPrice attribute.
    tp_order.lmtPrice = round(new_tp_price, 2)

    # Submit the modified orders. In IB, some orders can be modified if they have not been triggered.
    ib.placeOrder(contract, sl_order)
    ib.placeOrder(contract, tp_order)

# Optionally, disconnect when done.
ib.disconnect()
