import asyncio
import time
import PyQt5.QtWidgets as qt
from PyQt5.QtWidgets import (
    QTableWidgetItem, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QWidget, QLabel, QTableWidget
)
from PyQt5.QtCore import Qt, QTimer
from ib_insync import IB, util, Stock
import numpy as np
import pandas as pd
import statsmodels.api as sm

###############################################################################
# Helper functions
###############################################################################

def make_duration_str(days: int) -> str:
    """Convert day count to IB-friendly durationStr."""
    if days <= 365:
        return f"{days} D"
    else:
        years = days // 365
        if years < 1:
            years = 1
        return f"{years} Y"

def computeDailyRegressions(df_daily: pd.DataFrame, lb: int) -> pd.DataFrame:
    """
    1) Slices the last `lb` rows of df_daily (with columns [open,high,low,close]),
    2) Performs OLS => build a DataFrame with columns [lr_value, lr_plus_2, lr_minus_2]
       for each daily row in that slice.

    If insufficient data => empty DataFrame.
    """
    if df_daily is None or df_daily.empty or len(df_daily) < lb or lb < 5:
        return pd.DataFrame()

    recent = df_daily.tail(lb).copy()
    closes = recent['close'].values
    X = np.arange(len(closes))
    X = sm.add_constant(X)
    model = sm.OLS(closes, X).fit()
    y_pred = model.predict(X)
    residuals = closes - y_pred
    sigma = np.std(residuals)

    df_pred = pd.DataFrame(index=recent.index)
    df_pred['lr_value'] = y_pred
    df_pred['lr_plus_2'] = df_pred['lr_value'] + 2*sigma
    df_pred['lr_minus_2'] = df_pred['lr_value'] - 2*sigma
    return df_pred

def mergeDailyPredictionsInto15Min(df_15m: pd.DataFrame, df_pred: pd.DataFrame) -> pd.DataFrame:
    """
    As-of merge. For each 15-min bar, we attach the "last known" daily row
    whose index <= bar's timestamp. This way each 15-min bar row has
    [lr_value, lr_plus_2, lr_minus_2].
    """
    if df_15m.empty or df_pred.empty:
        return pd.DataFrame()
    df_pred.index = pd.to_datetime(df_pred.index).tz_localize(df_15m.index.tz)

    df_15m = df_15m.sort_index()
    df_pred = df_pred.sort_index()

    merged = pd.merge_asof(
        df_15m,
        df_pred,
        left_index=True,
        right_index=True,
        direction='backward'
    )
    return merged

def findMostRecentHit(merged_15m: pd.DataFrame) -> (str, float):
    """
    1) Each 15-min row has [lr_value, lr_plus_2, lr_minus_2].
    2) Scan from the newest bar to the oldest to see if plus_2 or minus_2 or mean is in [low, high].
    3) Priority: lr_plus_2, lr_minus_2, lr_value (change if you prefer).
    4) Return (whichLine, lineVal) or (None, None).
    """
    if merged_15m.empty:
        print('merged_15 is empty')
        return (None, None)

    for i in range(len(merged_15m)-1, -1, -1):
        row = merged_15m.iloc[i]
        low_ = row['low']
        high_ = row['high']
        plus_ = row['lr_plus_2']
        minus_ = row['lr_minus_2']
        mean_ = row['lr_value']

        # check plus_2 first
        if low_ <= plus_ <= high_:
            return ("lr_plus_2", plus_)
        # minus_2
        if low_ <= minus_ <= high_:
            return ("lr_minus_2", minus_)
        # mean
        if low_ <= mean_ <= high_:
            return ("lr_value", mean_)

    return (None, None)

def compareToCurrentBar(merged_15m: pd.DataFrame, whichBand: str, lineVal: float) -> str:
    """
    Compare lineVal to the *latest* 15-min row's average => '++','--','+','-' or 'N/A'.
    """
    if not whichBand:
        return "N/A"
    if merged_15m.empty:
        return "N/A"

    latest = merged_15m.iloc[-1]
    avg_15m = (latest['open'] + latest['high'] + latest['low'] + latest['close']) / 4.0
    from_below = (avg_15m > lineVal)

    if whichBand in ("lr_plus_2", "lr_minus_2"):
        return "++" if from_below else "--"
    else:
        return "+" if from_below else "-"

###############################################################################
# TickerTable
###############################################################################
class TickerTable(qt.QTableWidget):
    """
    8 columns:
      0 Symbol
      1 Last (real-time)
      2 ShortLB (editable)
      3 MedLB   (editable)
      4 LongLB  (editable)
      5 ShortSignal
      6 MediumSignal
      7 LongSignal
    """
    headers = [
        'Symbol', 'Last',
        'ShortLB', 'MedLB', 'LongLB',
        'ShortSignal', 'MediumSignal', 'LongSignal'
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.conId2Row = {}
        self.setColumnCount(len(self.headers))
        self.setHorizontalHeaderLabels(self.headers)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(qt.QAbstractItemView.DoubleClicked)

    def __contains__(self, contract):
        return contract.conId in self.conId2Row

    def addTickerRow(self, ticker, shortLB=20, medLB=60, longLB=120):
        conId = ticker.contract.conId
        row = self.rowCount()
        self.insertRow(row)
        self.conId2Row[conId] = row

        for col in range(len(self.headers)):
            item = QTableWidgetItem('-')
            if col in (2,3,4):  # shortLB, medLB, longLB
                item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.setItem(row, col, item)

        self.item(row, 0).setText(ticker.contract.symbol)  # Symbol
        self.item(row, 1).setText('-')  # Last
        self.item(row, 2).setText(str(shortLB))
        self.item(row, 3).setText(str(medLB))
        self.item(row, 4).setText(str(longLB))

        self.resizeColumnsToContents()

    def onPendingTickers(self, tickers):
        """
        Update the 'Last' column (col=1) with real-time last price.
        """
        for t in tickers:
            row = self.conId2Row.get(t.contract.conId)
            if row is not None:
                last_item = self.item(row, 1)
                if t.last is not None:
                    last_item.setText(f"{t.last:.2f}")

    def setSignals(self, conId, shortSig, medSig, longSig):
        """
        Update columns 5,6,7 with the final signals.
        """
        row = self.conId2Row.get(conId)
        if row is None:
            return
        self.item(row,5).setText(shortSig)
        self.item(row,6).setText(medSig)
        self.item(row,7).setText(longSig)

    def clearTickers(self):
        self.setRowCount(0)
        self.conId2Row.clear()

###############################################################################
# MainWindow
###############################################################################
class MainWindow(qt.QWidget):
    """
    - Connect/Disconnect to IB
    - Add Tickers => table
    - "Compute Signals" => for each ticker:
       1) read shortLB, medLB, longLB
       2) single daily fetch for maxLB => produce 3 sets of predictions (short, med, long)
       3) 15-min bars => merge with each set => find most recent hit => compare => signal
       4) store signals in the table
    """

    def __init__(self, host='127.0.0.1', port=7497, clientId=1):
        super().__init__()
        self.ib = IB()
        self.ib.pendingTickersEvent += self.onPendingTickers

        self.connectInfo = (host, port, clientId)

        # UI
        self.connectBtn = QPushButton("Connect")
        self.connectBtn.clicked.connect(self.onConnectClicked)

        self.addLabel = QLabel("Add US Equity:")
        self.addEdit = QLineEdit("")
        self.addButton = QPushButton("Add Ticker")
        self.addButton.clicked.connect(self.onAddTicker)

        self.table = TickerTable()

        self.computeBtn = QPushButton("Compute Signals")
        self.computeBtn.clicked.connect(self.onComputeSignals)

        # Layout
        topLayout = QHBoxLayout()
        topLayout.addWidget(self.connectBtn)
        topLayout.addWidget(self.addLabel)
        topLayout.addWidget(self.addEdit)
        topLayout.addWidget(self.addButton)

        mainLayout = QVBoxLayout(self)
        mainLayout.addLayout(topLayout)
        mainLayout.addWidget(self.table)
        mainLayout.addWidget(self.computeBtn)

        self.setWindowTitle("PyQt + ib_insync: Final LR w/ 3 lookbacks + hits")

        # QTimer for auto signals (if desired)
        self.timer = QTimer()
        self.timer.setInterval(15*60*1000)  # 15 min in ms
        self.timer.timeout.connect(self.onComputeSignals)

        self.df_short, self.df_med, self.df_long = None, None, None
        # self.timer.start()  # uncomment to auto-run signals

    def onConnectClicked(self):
        if self.ib.isConnected():
            self.ib.disconnect()
            self.table.clearTickers()
            self.connectBtn.setText("Connect")
        else:
            self.ib.connect(*self.connectInfo)
            self.ib.reqMarketDataType(1)  # live
            self.connectBtn.setText("Disconnect")

    def onAddTicker(self):
        sym = self.addEdit.text().strip().upper()
        if not sym:
            return
        if not self.ib.isConnected():
            print("Not connected.")
            return
        contract = Stock(sym, 'SMART', 'USD')
        c = self.ib.qualifyContracts(contract)
        if c:
            ticker = self.ib.reqMktData(c[0], '', False, False)
            self.table.addTickerRow(ticker, shortLB=20, medLB=60, longLB=120)
        self.addEdit.clear()

    def onPendingTickers(self, tickers):
        self.table.onPendingTickers(tickers)

    def get_regressions(self):

        if not self.ib.isConnected():
            print("Not connected.")
            return

        for conId, rowIdx in self.table.conId2Row.items():
            # find Ticker
            found = None
            for t in self.ib.tickers():
                if t.contract.conId == conId:
                    found = t
                    break
            if not found:
                continue
            contract = found.contract

            # read shortLB, medLB, longLB from table
            shortLB_str = self.table.item(rowIdx, 2).text()
            medLB_str   = self.table.item(rowIdx, 3).text()
            longLB_str  = self.table.item(rowIdx, 4).text()
            try:
                shortLB = int(shortLB_str)
                medLB   = int(medLB_str)
                longLB  = int(longLB_str)
            except ValueError:
                self.table.setSignals(conId, "Err", "Err", "Err")
                continue

            maxLB = max(shortLB, medLB, longLB)
            if maxLB < 5:
                self.table.setSignals(conId, "NoData", "NoData", "NoData")
                continue

            # 1) daily fetch
            # e.g. 2 * maxLB => days. If > 365, use Y.
            days_needed = maxLB * 2
            durationStr = make_duration_str(days_needed)
            try:
                daily_bars = self.ib.reqHistoricalData(
                    contract,
                    endDateTime='',
                    durationStr=durationStr,
                    barSizeSetting='1 day',
                    whatToShow='TRADES',
                    useRTH=False,
                    keepUpToDate=False
                )
            except asyncio.TimeoutError:
                self.table.setSignals(conId, "Timeout", "Timeout", "Timeout")
                continue
            df_daily = util.df(daily_bars)
            if df_daily.empty or len(df_daily) < 5:
                self.table.setSignals(conId, "NoData", "NoData", "NoData")
                continue

            df_daily.set_index('date', inplace=True)

            # shortPred, medPred, longPred
            self.df_short = computeDailyRegressions(df_daily, shortLB)
            self.df_med   = computeDailyRegressions(df_daily, medLB)
            self.df_long  = computeDailyRegressions(df_daily, longLB)


    def onComputeSignals2(self):

        if not self.ib.isConnected():
            print("Not connected.")
            return

        for conId, rowIdx in self.table.conId2Row.items():
            # find Ticker
            found = None
            for t in self.ib.tickers():
                if t.contract.conId == conId:
                    found = t
                    break
            if not found:
                continue
            contract = found.contract

            # 2) 15-min bars
            # we just do ~ 15 days
            try:
                bars_15 = self.ib.reqHistoricalData(
                    contract,
                    endDateTime='',
                    durationStr='15 D',
                    barSizeSetting='15 mins',
                    whatToShow='TRADES',
                    useRTH=False,
                    keepUpToDate=False
                )
            except asyncio.TimeoutError:
                self.table.setSignals(conId, "Timeout", "Timeout", "Timeout")
                continue

            df15 = util.df(bars_15)
            if df15.empty:
                self.table.setSignals(conId, "NoData", "NoData", "NoData")
                continue

            df15.set_index('date', inplace=True)

            # short
            merged_short = mergeDailyPredictionsInto15Min(df15, self.df_short)
            wline_s, val_s = findMostRecentHit(merged_short)
            shortSig = compareToCurrentBar(merged_short, wline_s, val_s)

            # medium
            merged_med = mergeDailyPredictionsInto15Min(df15, self.df_med)
            wline_m, val_m = findMostRecentHit(merged_med)
            medSig = compareToCurrentBar(merged_med, wline_m, val_m)

            # long
            merged_long = mergeDailyPredictionsInto15Min(df15, self.df_long)
            wline_l, val_l = findMostRecentHit(merged_long)
            longSig = compareToCurrentBar(merged_long, wline_l, val_l)

            # store signals
            self.table.setSignals(conId, shortSig, medSig, longSig)

    def onComputeSignals(self):
        """
        For each ticker row:
          1) read shortLB, medLB, longLB
          2) single daily fetch for maxLB => build shortPred, medPred, longPred
          3) fetch 15-min bars => for each (short,med,long):
               - merge => find most recent hit => compare => signal
          4) store signals in table
        """
        if not self.ib.isConnected():
            print("Not connected.")
            return

        for conId, rowIdx in self.table.conId2Row.items():
            # find Ticker
            found = None
            for t in self.ib.tickers():
                if t.contract.conId == conId:
                    found = t
                    break
            if not found:
                continue
            contract = found.contract

            # read shortLB, medLB, longLB from table
            shortLB_str = self.table.item(rowIdx, 2).text()
            medLB_str   = self.table.item(rowIdx, 3).text()
            longLB_str  = self.table.item(rowIdx, 4).text()
            try:
                shortLB = int(shortLB_str)
                medLB   = int(medLB_str)
                longLB  = int(longLB_str)
            except ValueError:
                self.table.setSignals(conId, "Err", "Err", "Err")
                continue

            maxLB = max(shortLB, medLB, longLB)
            if maxLB < 5:
                self.table.setSignals(conId, "NoData", "NoData", "NoData")
                continue

            # 1) daily fetch
            # e.g. 2 * maxLB => days. If > 365, use Y.
            days_needed = maxLB * 2
            durationStr = make_duration_str(days_needed)
            try:
                daily_bars = self.ib.reqHistoricalData(
                    contract,
                    endDateTime='',
                    durationStr=durationStr,
                    barSizeSetting='1 day',
                    whatToShow='TRADES',
                    useRTH=False,
                    keepUpToDate=False
                )
            except asyncio.TimeoutError:
                self.table.setSignals(conId, "Timeout", "Timeout", "Timeout")
                continue
            df_daily = util.df(daily_bars)
            if df_daily.empty or len(df_daily) < 5:
                self.table.setSignals(conId, "NoData", "NoData", "NoData")
                continue

            df_daily.set_index('date', inplace=True)

            # shortPred, medPred, longPred
            df_short = computeDailyRegressions(df_daily, shortLB)
            df_med   = computeDailyRegressions(df_daily, medLB)
            df_long  = computeDailyRegressions(df_daily, longLB)

            self.df_short, self.df_med, self.df_long = df_short, df_med, df_long

            # 2) 15-min bars
            # we just do ~ 15 days
            try:
                bars_15 = self.ib.reqHistoricalData(
                    contract,
                    endDateTime='',
                    durationStr='15 D',
                    barSizeSetting='15 mins',
                    whatToShow='TRADES',
                    useRTH=False,
                    keepUpToDate=False
                )
            except asyncio.TimeoutError:
                self.table.setSignals(conId, "Timeout", "Timeout", "Timeout")
                continue

            df15 = util.df(bars_15)
            if df15.empty:
                self.table.setSignals(conId, "NoData", "NoData", "NoData")
                continue

            df15.set_index('date', inplace=True)

            # short
            merged_short = mergeDailyPredictionsInto15Min(df15, df_short)
            wline_s, val_s = findMostRecentHit(merged_short)
            shortSig = compareToCurrentBar(merged_short, wline_s, val_s)

            # medium
            merged_med = mergeDailyPredictionsInto15Min(df15, df_med)
            wline_m, val_m = findMostRecentHit(merged_med)
            medSig = compareToCurrentBar(merged_med, wline_m, val_m)

            # long
            merged_long = mergeDailyPredictionsInto15Min(df15, df_long)
            wline_l, val_l = findMostRecentHit(merged_long)
            longSig = compareToCurrentBar(merged_long, wline_l, val_l)

            # store signals
            self.table.setSignals(conId, shortSig, medSig, longSig)

    def closeEvent(self, ev):
        loop = util.getLoop()
        loop.stop()



###############################################################################
# Launch
if __name__ == '__main__':
    util.patchAsyncio()
    util.useQt()

    window = MainWindow('127.0.0.1', 7497, 1)
    window.resize(900, 500)
    window.show()

    # Optionally start auto signals:
    # window.timer.start()

    IB.run()
