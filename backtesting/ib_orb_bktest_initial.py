# -*- coding: utf-8 -*-
"""
IB API - Backtesting Open Range Breakout Strategy
"""
from ib_insync import *
# Import libraries
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
import pandas as pd
import threading
import time
from copy import deepcopy

tickers = ["AAPL", 'TSLA', 'IBKR', 'META', 'NVDA']


class TradeApp(EWrapper, EClient):
    def __init__(self): 
        EClient.__init__(self, self) 
        self.data = {}
        self.skip = False
        
    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=''):
        print("Error {} {} {}".format(reqId,errorCode,errorString))
        if reqId !=-1:
            self.skip = True
            print("skipping calculations")
            ticker_event.set()
        
    def historicalData(self, reqId, bar):
        if reqId not in self.data:
            self.data[reqId] = pd.DataFrame([{"Date":bar.date,"Open":bar.open,"High":bar.high,"Low":bar.low,"Close":bar.close,"Volume":bar.volume}])
        else:
            self.data[reqId] = pd.concat((self.data[reqId],pd.DataFrame([{"Date":bar.date,"Open":bar.open,"High":bar.high,"Low":bar.low,"Close":bar.close,"Volume":bar.volume}])))

            #self.data[reqId].append({"Date":bar.date,"Open":bar.open,"High":bar.high,"Low":bar.low,"Close":bar.close,"Volume":bar.volume})
        #print("reqID:{}, date:{}, open:{}, high:{}, low:{}, close:{}, volume:{}".format(reqId,bar.date,bar.open,bar.high,bar.low,bar.close,bar.volume))

          
    def historicalDataEnd(self, reqId, start, end):
        super().historicalDataEnd(reqId, start, end)

        df = self.data.get(reqId, None)
        if df is not None and not df.empty:
            # Check the first row's date format
            date_str = df.iloc[0]["Date"]
            if " " in date_str:
                # likely intraday => parse with %Y%m%d  %H:%M:%S
                df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d  %H:%M:%S")
            else:
                # daily => parse with %Y%m%d
                df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d")

            df.set_index("Date", inplace=True)
            df.sort_index(inplace=True)
            self.data[reqId] = df

        print("HistoricalDataEnd. ReqId:", reqId, "from", start, "to", end)

        self.skip = False
        ticker_event.set()

def usTechStk(symbol,sec_type="STK",currency="USD",exchange="ISLAND"):
    contract = Contract()
    contract.symbol = symbol
    contract.secType = sec_type
    contract.currency = currency
    contract.exchange = exchange
    return contract 

def histData(req_num,contract,endDate,duration,candle_size):
    """extracts historical data"""
    app.reqHistoricalData(reqId=req_num, 
                          contract=contract,
                          endDateTime=endDate,
                          durationStr=duration,
                          barSizeSetting=candle_size,
                          whatToShow='TRADES',
                          useRTH=1,
                          formatDate=1,
                          keepUpToDate=0,
                          chartOptions=[])	 # EClient function to request contract details

def connection():
    app.run()

ticker_event = threading.Event()
data_event = threading.Event()

app = TradeApp()
app.connect(host='127.0.0.1', port=7497, clientId=24) #port 4002 for ib gateway paper trading/7497 for TWS paper trading

con_thread = threading.Thread(target=connection, daemon=True)
con_thread.start()
time.sleep(2) # some latency added to ensure that the connection is established


for ticker in tickers:
    try:
        ticker_event.clear()
        histData(tickers.index(ticker),usTechStk(ticker),'','1 M', '1 day',)
        ticker_event.wait()
    except Exception as e:
        print(e)
        print("unable to extract data for {}".format(ticker))

#extract and store historical data in dataframe
#historicalData = dataDataframe(tickers,app)
#time.sleep(1)
data = deepcopy(app.data)

for hd in data:
    data[hd]["Gap"] = ((data[hd]["Open"]/data[hd]["Close"].shift(1))-1)*100
    data[hd]["AvVol"] = data[hd]["Volume"].rolling(5).mean().shift(1)
    data[hd].dropna(inplace=True)

def topGap(data, tickers):

    top_gap_by_date = {}

    reference_key = list(data.keys())[0]
    ref_df = data[reference_key]
    dates = ref_df.index

    ticker_mapping = {req_id: ticker for req_id, ticker in enumerate(tickers)}

    for date in dates:
        gap_map = {}
        for reqid, df in data.items():
            ticker = ticker_mapping[reqid]
            if date in df.index:
                gap_map[ticker] = df.loc[date, 'Gap']
            else:
                # If date is missing in this DF, store NaN
                gap_map[ticker] = float('nan')

        # Convert to a Series for easy sorting
        gap_series = pd.Series(gap_map)

        # Drop the NaNs so they don't appear as "top"
        gap_series.dropna(inplace=True)

        # Sort descending by gap value and pick top 2
        top_2 = gap_series.sort_values(ascending=False).head(2)

        # Store the tickers (and optionally the gap values) in your output
        top_gap_by_date[date] = top_2.index.tolist()

    return top_gap_by_date

top_gap_by_date = topGap(data, tickers)


def backtest(top_gap_by_date, data, app):
    """
    Backtest using intraday data with DateTimeIndex, where top_gap_by_date keys
    are daily dates (e.g. 2024-12-09 00:00:00). We then request intraday data
    for each ticker on that date, parse/sort it, and run the logic.
    """
    date_stats = {}
    reqID = 1000

    for daily_date in top_gap_by_date:
        date_stats[daily_date] = {}

        # Convert daily_date (which is something like 2024-12-09 00:00:00) into a string for IB's reqHistoricalData
        day_str = daily_date.strftime("%Y%m%d")  # '20241209'
        end_datetime = day_str + " 22:05:00 US/Eastern"

        for ticker in top_gap_by_date[daily_date]:
            ticker_event.clear()

            # Request intraday data for this ticker on that day
            histData(reqID, usTechStk(ticker), end_datetime, '1 D', '5 mins')
            ticker_event.wait()

            # If IB returned an error, skip
            if app.skip:
                continue
                reqID += 1

            # Give IB a small pause to avoid race conditions
            time.sleep(3.5)

            # Make sure we actually have data
            intraday_df = app.data.get(reqID, pd.DataFrame())
            if intraday_df.empty:
                # No intraday data for that date/ticker pair, skip
                reqID += 1
                continue

            # We pick the “first” bar as the reference for hi_price, lo_price.
            # If the day is outside RTH, you might need to select only RTH times, etc.
            first_bar = intraday_df.iloc[0]
            hi_price = first_bar["High"]
            lo_price = first_bar["Low"]

            open_price = ''
            direction = ''
            date_stats[daily_date][ticker] = 0.0

            # Loop through bars from 2nd row onward
            for i in range(1, len(intraday_df)):
                prev_bar = intraday_df.iloc[i - 1]
                current_bar = intraday_df.iloc[i]

                # Safeguard for referencing the i+1 bar for the fill price:
                if i >= len(intraday_df) - 1:
                    # If we can't safely do i+1, break out
                    break

                next_bar = intraday_df.iloc[i + 1]

                # Check for volume spike condition, etc.
                if prev_bar["Volume"] > 2 * (data[ticker].loc[daily_date, "AvVol"] / 78) and open_price == '':
                    # Long breakout:
                    if current_bar["High"] > hi_price:
                        open_price = 0.8 * next_bar["Open"] + 0.2 * next_bar["High"]
                        direction = 'long'
                    # Short breakout:
                    elif current_bar["Low"] < lo_price:
                        open_price = 0.8 * next_bar["Open"] + 0.2 * next_bar["Low"]
                        direction = 'short'

                # If we opened a position, check for exit conditions
                if open_price != '':
                    if direction == 'long':
                        # Hit +5%
                        if current_bar["High"] > (hi_price * 1.05):
                            ticker_return = ((hi_price * 1.05) / open_price) - 1
                            date_stats[daily_date][ticker] = ticker_return
                            break
                        # Hit stop
                        elif current_bar["Low"] < lo_price:
                            ticker_return = (lo_price / open_price) - 1
                            date_stats[daily_date][ticker] = ticker_return
                            break
                        else:
                            # Ongoing bar – update PnL to last close
                            ticker_return = (current_bar["Close"] / open_price) - 1
                            date_stats[daily_date][ticker] = ticker_return

                    elif direction == 'short':
                        # Reached -5% from open
                        if current_bar["Low"] < (lo_price * 0.95):
                            ticker_return = 1 - ((lo_price * 0.95) / open_price)
                            date_stats[daily_date][ticker] = ticker_return
                            break
                        # Hit stop
                        elif current_bar["High"] > hi_price:
                            ticker_return = 1 - (hi_price / open_price)
                            date_stats[daily_date][ticker] = ticker_return
                            break
                        else:
                            # Ongoing bar – update PnL to last close
                            ticker_return = 1 - (current_bar["Close"] / open_price)
                            date_stats[daily_date][ticker] = ticker_return

            # Increment reqID for the next request
            reqID += 1

    return date_stats
                    
date_stats = backtest(top_gap_by_date, data, app)


###########################KPIs#####################################
def abs_return(date_stats):
    df = pd.DataFrame(date_stats).T
    df["ret"] = 1+df.mean(axis=1)
    cum_ret = (df["ret"].cumprod() - 1)[-1]
    return  cum_ret

def win_rate(date_stats):
    win_count = 0
    lose_count = 0
    for i in date_stats:
        for ret in date_stats[i]:
            if date_stats[i][ret] > 0:
                win_count+=1
            elif date_stats[i][ret] < 0:
                lose_count+=1
    return (win_count/(win_count+lose_count))*100

def mean_ret_winner(date_stats):
    win_ret = []
    for i in date_stats:
        for ret in date_stats[i]:
            if date_stats[i][ret] > 0:
                win_ret.append(date_stats[i][ret])                
    return sum(win_ret)/len(win_ret)

def mean_ret_loser(date_stats):
    los_ret = []
    for i in date_stats:
        for ret in date_stats[i]:
            if date_stats[i][ret] < 0:
                los_ret.append(date_stats[i][ret])                
    return sum(los_ret)/len(los_ret)


print("**********Strategy Performance Statistics**********")
print("total cumulative return = {}".format(round(abs_return(date_stats),4)))
print("total win rate = {}".format(round(win_rate(date_stats),2)))
print("mean return per win trade = {}".format(round(mean_ret_winner(date_stats),4)))
print("mean return per loss trade = {}".format(round(mean_ret_loser(date_stats),4)))