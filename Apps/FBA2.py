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
    1) Slices the last `lb` rows of df_daily,
    2) Performs OLS => returns a DataFrame with [lr_value, lr_plus_2, lr_minus_2].
    If insufficient data => empty DF.
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
    Merge df_pred (daily lines) into df_15m (15-min bars) with an as-of merge.
    Both must have a DateTimeIndex. We also ensure they share the same tz.
    """
    if df_15m.empty or df_pred.empty:
        return pd.DataFrame()

    # Match time zones (if df_15m is tz-aware)
    if df_15m.index.tz is not None:
        df_pred.index = pd.to_datetime(df_pred.index).tz_localize(df_15m.index.tz)

    df_15m = df_15m.sort_index()
    df_pred = df_pred.sort_index()

    merged = pd.merge_asof(
        df_15m, df_pred,
        left_index=True,
        right_index=True,
        direction='backward'
    )
    return merged


def findMostRecentHit(merged_15m: pd.DataFrame) -> (str, float):
    """
    Scan from newest to oldest 15-min bar. Check if lr_plus_2, lr_minus_2, or lr_value
    is in [low, high]. Priority: +2σ, -2σ, mean.
    Return (whichLine, lineVal) or (None,None).
    """
    if merged_15m.empty:
        return (None, None)

    for i in range(len(merged_15m)-1, -1, -1):
        row = merged_15m.iloc[i]
        low_, high_ = row['low'], row['high']
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


def compareToCurrentBar(merged_15m: pd.DataFrame, whichLine: str, lineVal: float) -> str:
    """
    Compare lineVal to the *latest* 15-min bar's average => '++','--','+','-' or 'N/A'.
    """
    if not whichLine or merged_15m.empty:
        return "N/A"

    latest = merged_15m.iloc[-1]
    avg_15m = (latest['open'] + latest['high'] + latest['low'] + latest['close']) / 4.0
    from_below = (avg_15m > lineVal)

    if whichLine in ("lr_plus_2", "lr_minus_2"):
        return "++" if from_below else "--"
    else:
        return "+" if from_below else "-"


###############################################################################
# TickerTable
###############################################################################
class TickerTable(qt.QTableWidget):
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

        # fill basic info
        self.item(row, 0).setText(ticker.contract.symbol)  # Symbol
        self.item(row, 1).setText('-')  # Last
        self.item(row, 2).setText(str(shortLB))
        self.item(row, 3).setText(str(medLB))
        self.item(row, 4).setText(str(longLB))

        self.resizeColumnsToContents()

    def onPendingTickers(self, tickers):
        for t in tickers:
            row = self.conId2Row.get(t.contract.conId)
            if row is not None and t.last is not None:
                last_item = self.item(row, 1)
                last_item.setText(f"{t.last:.2f}")

    def setSignals(self, conId, shortSig, medSig, longSig):
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
    - We have 2 steps:
       1) "Update Regressions" => fetch daily data, produce short/med/long predictions, store in self.regressions_dict[conId].
       2) "Compute Signals" => fetch 15-min data, do merges/hits => table signals.

    - If user tries to compute signals without having regressions, we show a message.

    - A QTimer calls 'Compute Signals' automatically every 15 min.
    """

    def __init__(self, host='127.0.0.1', port=7497, clientId=1):
        super().__init__()
        self.ib = IB()
        self.ib.pendingTickersEvent += self.onPendingTickers

        self.connectInfo = (host, port, clientId)

        # Dictionary to store per-ticker predictions:
        # self.regressions_dict[conId] = {
        #   "shortPred": df_short,  # daily lines
        #   "medPred":   df_med,
        #   "longPred":  df_long
        # }
        self.regressions_dict = {}

        # UI
        self.connectBtn = QPushButton("Connect")
        self.connectBtn.clicked.connect(self.onConnectClicked)

        self.addLabel = QLabel("Add US Equity:")
        self.addEdit = QLineEdit("")
        self.addButton = QPushButton("Add Ticker")
        self.addButton.clicked.connect(self.onAddTicker)

        self.table = TickerTable()

        self.updateRegBtn = QPushButton("Update Regressions")
        self.updateRegBtn.clicked.connect(self.onUpdateRegressions)

        self.signalsBtn = QPushButton("Compute Signals")
        self.signalsBtn.clicked.connect(self.onComputeSignals)

        # Layout
        topLayout = QHBoxLayout()
        topLayout.addWidget(self.connectBtn)
        topLayout.addWidget(self.addLabel)
        topLayout.addWidget(self.addEdit)
        topLayout.addWidget(self.addButton)

        mainLayout = QVBoxLayout(self)
        mainLayout.addLayout(topLayout)
        mainLayout.addWidget(self.table)

        bottomLayout = QHBoxLayout()
        bottomLayout.addWidget(self.updateRegBtn)
        bottomLayout.addWidget(self.signalsBtn)
        mainLayout.addLayout(bottomLayout)

        self.setWindowTitle("PyQt + ib_insync: Split Regressions vs. Signals")

        # QTimer for auto signals
        self.timer = QTimer()
        self.timer.setInterval(15*60*1000)  # 15 min
        self.timer.timeout.connect(self.onComputeSignals)
        # self.timer.start()  # optionally start auto updates

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

    ###########################################################################
    # Step 1: "Update Regressions"
    ###########################################################################
    def onUpdateRegressions(self):
        """
        For each ticker, fetch daily bars (based on largest LB),
        compute shortPred, medPred, longPred => store in self.regressions_dict[conId].
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

            # read shortLB, medLB, longLB
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

            days_needed = maxLB * 2
            durationStr = make_duration_str(days_needed)
            print(f"Updating daily regs for {contract.symbol}, LB={shortLB,medLB,longLB}, dur={durationStr}")

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
            df_short = computeDailyRegressions(df_daily, shortLB)
            df_med   = computeDailyRegressions(df_daily, medLB)
            df_long  = computeDailyRegressions(df_daily, longLB)

            self.regressions_dict[conId] = {
                "shortPred": df_short,
                "medPred":   df_med,
                "longPred":  df_long
            }
            print(f"{contract.symbol} => updated regressions.")

    ###########################################################################
    # Step 2: "Compute Signals"
    ###########################################################################
    def onComputeSignals(self):
        """
        For each ticker, if we have daily predictions stored,
        then fetch 15-min bars => merge + find hits => table signals.
        Otherwise, ask user to "Update Regressions" first.
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

            # do we have predictions?
            preds = self.regressions_dict.get(conId)
            if not preds:
                self.table.setSignals(conId, "UpdateFirst", "UpdateFirst", "UpdateFirst")
                continue

            df_short = preds["shortPred"]
            df_med   = preds["medPred"]
            df_long  = preds["longPred"]

            if df_short.empty or df_med.empty or df_long.empty:
                self.table.setSignals(conId, "NoData", "NoData", "NoData")
                continue

            print(f"Computing signals for {contract.symbol} ...")

            # fetch 15-min bars
            try:
                bars_15 = self.ib.reqHistoricalData(
                    contract,
                    endDateTime='',
                    durationStr='25 D',
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
                self.table.setSignals(conId, "No15m", "No15m", "No15m")
                continue

            df15.set_index('date', inplace=True)

            # short
            merged_s = mergeDailyPredictionsInto15Min(df15, df_short)
            b_s, v_s = findMostRecentHit(merged_s)
            shortSig = compareToCurrentBar(merged_s, b_s, v_s)

            # med
            merged_m = mergeDailyPredictionsInto15Min(df15, df_med)
            b_m, v_m = findMostRecentHit(merged_m)
            medSig = compareToCurrentBar(merged_m, b_m, v_m)

            # long
            merged_l = mergeDailyPredictionsInto15Min(df15, df_long)
            b_l, v_l = findMostRecentHit(merged_l)
            longSig = compareToCurrentBar(merged_l, b_l, v_l)

            self.table.setSignals(conId, shortSig, medSig, longSig)
            print(f'Computed Signals for {contract.symbol}')

    def closeEvent(self, event):
        loop = util.getLoop()
        loop.stop()


###############################################################################
# Launch
###############################################################################
if __name__ == '__main__':
    util.patchAsyncio()
    util.useQt()

    window = MainWindow('127.0.0.1', 7497, 1)
    window.resize(900, 500)
    window.show()

    # Optionally start auto signals:
    window.timer.start()

    IB.run()
