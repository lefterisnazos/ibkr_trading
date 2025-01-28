import asyncio
import time
import PyQt5.QtWidgets as qt
from PyQt5.QtWidgets import (
    QTableWidgetItem, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QWidget, QLabel
)
from PyQt5.QtCore import Qt
from ib_insync import IB, util, Stock
import statsmodels.api as sm
import numpy as np
import pandas as pd

class TickerTable(qt.QTableWidget):
    """
    Columns:
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
        'Symbol',
        'Last',
        'ShortLB',
        'MedLB',
        'LongLB',
        'ShortSignal',
        'MediumSignal',
        'LongSignal'
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.conId2Row = {}
        self.setColumnCount(len(self.headers))
        self.setHorizontalHeaderLabels(self.headers)
        self.setAlternatingRowColors(True)

        # Allow user to edit the LB columns
        self.setEditTriggers(qt.QAbstractItemView.DoubleClicked)

    def __contains__(self, contract):
        return contract.conId in self.conId2Row

    def addTickerRow(self, ticker, shortLB=20, medLB=60, longLB=120):
        """
        Creates a new row for this ticker.
        conId2Row is used to map the contract's conId to the row index.
        """
        conId = ticker.contract.conId
        row = self.rowCount()
        self.insertRow(row)
        self.conId2Row[conId] = row

        # Make placeholders
        for col in range(len(self.headers)):
            item = QTableWidgetItem('-')
            # Mark lookback columns as editable
            if col in (2, 3, 4):
                item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.setItem(row, col, item)

        self.item(row, 0).setText(ticker.contract.symbol)  # Symbol
        self.item(row, 1).setText('-')                     # Last
        self.item(row, 2).setText(str(shortLB))            # ShortLB
        self.item(row, 3).setText(str(medLB))              # MedLB
        self.item(row, 4).setText(str(longLB))             # LongLB

        self.resizeColumnsToContents()

    def onPendingTickers(self, tickers):
        """
        Update the 'Last' column (col=1) with the real-time last price.
        """
        for t in tickers:
            row = self.conId2Row.get(t.contract.conId)
            if row is None:
                continue
            last_item = self.item(row, 1)
            if t.last is not None:
                last_item.setText(f"{t.last:.2f}")

    def setSignalText(self, conId, shortSig, medSig, longSig):
        """
        Update the ShortSignal (5), MediumSignal (6), LongSignal (7) columns.
        """
        row = self.conId2Row.get(conId)
        if row is None:
            return
        self.item(row, 5).setText(shortSig)
        self.item(row, 6).setText(medSig)
        self.item(row, 7).setText(longSig)

    def clearTickers(self):
        self.setRowCount(0)
        self.conId2Row.clear()

class MainWindow(qt.QWidget):
    def __init__(self, host='127.0.0.1', port=7497, clientId=1):
        super().__init__()

        self.ib = IB()
        self.ib.pendingTickersEvent += self.onPendingTickers
        self.connectInfo = (host, port, clientId)

        # GUI
        self.connectButton = QPushButton("Connect")
        self.connectButton.clicked.connect(self.onConnectButtonClicked)

        self.addLabel = QLabel("Add US Equity (symbol): ")
        self.addEdit = QLineEdit("")
        self.addButton = QPushButton("Add Ticker")
        self.addButton.clicked.connect(self.onAddTickerClicked)

        self.table = TickerTable()
        self.computeButton = QPushButton("Compute LR Signals")
        self.computeButton.clicked.connect(self.onComputeLRSignals)

        # Layout
        topLayout = QHBoxLayout()
        topLayout.addWidget(self.addLabel)
        topLayout.addWidget(self.addEdit)
        topLayout.addWidget(self.addButton)

        mainLayout = QVBoxLayout(self)
        mainLayout.addWidget(self.connectButton)
        mainLayout.addLayout(topLayout)
        mainLayout.addWidget(self.table)
        mainLayout.addWidget(self.computeButton)

        self.setWindowTitle("ib_insync + PyQt: LR Signals w/ Fallback")

    def onConnectButtonClicked(self):
        """
        Toggle connect/disconnect to IB.
        """
        if self.ib.isConnected():
            self.ib.disconnect()
            self.table.clearTickers()
            self.connectButton.setText("Connect")
        else:
            self.ib.connect(*self.connectInfo)
            self.ib.reqMarketDataType(1)  # 1=live
            self.connectButton.setText("Disconnect")

    def onAddTickerClicked(self):
        """
        Add a US equity stock row (by symbol) if connected.
        """
        symbol = self.addEdit.text().strip().upper()
        if not symbol:
            return
        if not self.ib.isConnected():
            print("Not connected, can't add ticker.")
            return
        contract = Stock(symbol, 'SMART', 'USD')
        qualified = self.ib.qualifyContracts(contract)
        if qualified and contract.conId not in self.table.conId2Row:
            ticker = self.ib.reqMktData(contract)
            self.table.addTickerRow(ticker, shortLB=20, medLB=60, longLB=120)
        self.addEdit.clear()

    def onPendingTickers(self, tickers):
        self.table.onPendingTickers(tickers)

    def onComputeLRSignals(self):
        """
        For each row:
          - read shortLB, medLB, longLB
          - pick maxLB, fetch daily bars for ~2*maxLB days
          - slice for short, med, long
          - do LR => final predicted => compare to current price or fallback => "From Above/Below"
        """
        if not self.ib.isConnected():
            print("Not connected, cannot compute signals.")
            return

        barSize = '1 day'

        for conId, rowIdx in self.table.conId2Row.items():
            # find the Ticker
            ticker = None
            for t in self.ib.tickers():
                if t.contract.conId == conId:
                    ticker = t
                    break
            if not ticker:
                continue

            # read shortLB, medLB, longLB
            shortLB_str = self.table.item(rowIdx, 2).text()
            medLB_str   = self.table.item(rowIdx, 3).text()
            longLB_str  = self.table.item(rowIdx, 4).text()

            try:
                shortLB = int(shortLB_str)
                medLB   = int(medLB_str)
                longLB  = int(longLB_str)
            except ValueError:
                self.table.setSignalText(conId, "InvalidLB", "InvalidLB", "InvalidLB")
                continue

            maxLB = max(shortLB, medLB, longLB)
            if maxLB < 5:
                self.table.setSignalText(conId, "No Data", "No Data", "No Data")
                continue

            # single historical request
            durationStr = f'{int(maxLB * 1.5)} D'
            try:
                bars = self.ib.reqHistoricalData(
                    ticker.contract,
                    endDateTime='',
                    durationStr=durationStr,
                    barSizeSetting=barSize,
                    whatToShow='TRADES',
                    useRTH=False,
                    keepUpToDate=False
                )
            except asyncio.TimeoutError:
                print(f"Timeout fetching data for {ticker.contract.symbol}")
                self.table.setSignalText(conId, "Timeout", "Timeout", "Timeout")
                continue

            df = util.df(bars)
            if df.empty or len(df) < 5:
                self.table.setSignalText(conId, "No Data", "No Data", "No Data")
                continue

            df.set_index('date', inplace=True)

            # get "current price" from the Last column (real-time)
            current_str = self.table.item(rowIdx, 1).text()
            try:
                current_price = float(current_str)
            except ValueError:
                # user typed something or no real-time price
                current_price = None

            # fallback if no real-time price
            if current_price is None or current_price <= 0:
                # last bar's close from historical
                current_price = df['close'].iloc[-1]

            current_price_bar = {'open':df['open'].iloc[-1], 'high':df['high'].iloc[-1], 'low': df['low'].iloc[-1], 'close': df['close'].iloc[-1]}

            # compute short, med, long
            shortSignal  = self._computeOneSignal(df, shortLB,  current_price_bar)
            mediumSignal = self._computeOneSignal(df, medLB,    current_price_bar)
            longSignal   = self._computeOneSignal(df, longLB,   current_price_bar)

            self.table.setSignalText(conId, shortSignal, mediumSignal, longSignal)

    def _computeOneSignal(
            self,
            daily_df: pd.DataFrame,
            lb: int,
            bar15m: dict
    ) -> str:
        """
        daily_df: DataFrame of daily bars with columns [open, high, low, close].
        lb: number of bars to consider (lookback).
        bar15m: a dict with {'open', 'high', 'low', 'close'} for the last 15-min bar.
                We'll compute the average = (o + h + l + c) / 4 as the "current price."

        Steps:
          1) If daily_df < lb or lb < 5 => "No Data".
          2) Slice last lb rows, do OLS => get lr_value, ±2σ.
          3) Scan from newest to oldest daily bar to see which line
             (lr_plus_2sigma, lr_minus_2sigma, lr_value) was hit most recently.
             - 'Hit' means that line_value is between [bar.low, bar.high].
             - Check in a certain priority or any order you like.
          4) If no line is found => "N/A".
          5) If found, compare that line_value with the average of the 15-min bar:
             if (avg15m > line_value) => "From Below", else "From Above".
        """
        # 1) Check data sufficiency
        if len(daily_df) < lb or lb < 5:
            return "No Data"

        # slice last lb bars
        recent = daily_df.tail(lb).copy()
        # We'll regress on 'close' by default
        closes = recent['close'].values

        # 2) OLS regression
        X = np.arange(len(closes))
        X = sm.add_constant(X)  # intercept
        model = sm.OLS(closes, X).fit()
        y_pred = model.predict(X)
        residuals = closes - y_pred
        sigma = np.std(residuals)

        lr_value = y_pred[-1]
        lr_plus_2sigma = lr_value + 2 * sigma
        lr_minus_2sigma = lr_value - 2 * sigma

        # 3) Find the most recently hit line
        # We'll define "hit" as line_value in [low, high].
        # We'll scan from newest daily bar to oldest.
        which_line = None
        line_val = None

        # define a priority order if you like, or check in some order
        # for each bar, we see if plus_2sigma is in [low, high], else minus_2sigma, else lr_value
        # adapt if you'd rather do a different order.
        for i in range(len(recent) - 1, -1, -1):
            row = recent.iloc[i]
            bar_low = row['low']
            bar_high = row['high']

            # check plus_2σ
            if bar_low <= lr_plus_2sigma <= bar_high:
                which_line = 'lr_plus_2sigma'
                line_val = lr_plus_2sigma
                break
            # check minus_2σ
            elif bar_low <= lr_minus_2sigma <= bar_high:
                which_line = 'lr_minus_2sigma'
                line_val = lr_minus_2sigma
                break
            # check mean
            elif bar_low <= lr_value <= bar_high:
                which_line = 'lr_value'
                line_val = lr_value
                break

        if which_line is None:
            # no line was hit
            return "N/A"

        # 4) Compare last 15-min bar average
        # bar15m is a dict like {'open': float, 'high': float, 'low': float, 'close': float}
        o = bar15m.get('open', 0)
        h = bar15m.get('high', 0)
        l = bar15m.get('low', 0)
        c = bar15m.get('close', 0)
        avg_15m = (o + h + l + c) / 4.0

        # if the average is bigger => "From Below" (i.e. price is above that line)
        if avg_15m > line_val:
            return "From Below"
        else:
            return "From Above"

    def closeEvent(self, ev):
        # Called when window closes
        loop = util.getLoop()
        loop.stop()

if __name__ == '__main__':
    util.patchAsyncio()
    util.useQt()

    window = MainWindow('127.0.0.1', 7497, 1)
    window.resize(800, 400)
    window.show()

    # Start the ib_insync + Qt event loop
    IB.run()
