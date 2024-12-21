# -*- coding: utf-8 -*-
"""
IBAPI - Functions that have changed in later IBAPI versions and require update

@author: Mayank Rasu (http://rasuquant.com/wp/)
"""
from ibapi.order import Order

#the signature of error function of EWrapper class was changed and advancedOrderRejectJson has been added       
def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
    print("Error {} {} {}".format(reqId,errorCode,errorString))

#the signature of error function of EWrapper class was changed and advancedOrderRejectJson has been added           
def tickOptionComputation(self, reqId, tickType, tickAttrib, impliedVol, delta, 
                          optPrice, pvDividend, gamma, vega, theta, undPrice):
    super().tickOptionComputation(reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, 
                                  gamma, vega, theta, undPrice)
    print("option greeks: delta = {}, gamma = {}".format(delta,gamma))

#candelOrder function of EClient class was changed and a mandatory manualCancelOrderTime 
#argument was added to it which can be left blank as shown below   
app.cancelOrder(order_id, "")

    
#two additional mandatory attributes (eTradeOnly and firmQuoteOnly) were added to the order object
def lmtOrder(direction,quantity,lmt_price):
    order = Order()
    order.action = direction
    order.orderType = "LMT"
    order.totalQuantity = quantity
    order.lmtPrice = lmt_price
    order.eTradeOnly = ""
    order.firmQuoteOnly = ""
    return order