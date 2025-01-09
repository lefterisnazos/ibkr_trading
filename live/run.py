from LinearRegStrategy import *
from ib_client_live import *
from live_trading_runner import *


strategy = LinearRegSigmaStrategyLive(ib_client= IBClientLive(account='DU8057891'), medium_lookback=2, long_lookback=5)
runner = LiveRunner(strategy)
runner.start()

X=2