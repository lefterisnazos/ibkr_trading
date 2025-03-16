import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Define tickers for IBIT and MSTR
ibit_ticker = "IBIT"  # Replace with the correct ticker symbol if different
mstr_ticker = "MSTR"

# Set the start date to 60 days ago (15m data is only available for the past 60 days)
start_date = (datetime.today() - timedelta(days=60)).strftime('%Y-%m-%d')

# Download historical data using 15-minute intervals
ibit_data = yf.download(ibit_ticker, start=start_date, )
mstr_data = yf.download(mstr_ticker, start=start_date, )

# Ensure data is not empty
if ibit_data.empty or mstr_data.empty:
    raise ValueError("One or both data downloads returned empty. Adjust your ticker symbols or date range.")

# Merge the two datasets on the datetime index using the 'Close' price
data = pd.DataFrame({
    'IBIT_Close': ibit_data['Close'],
    'MSTR_Close': mstr_data['Close']
}).dropna()

# Calculate percentage returns for both assets
returns = data.pct_change().dropna()

# Compute covariance between MSTR and IBIT returns and the variance of IBIT returns
covariance = np.cov(returns['MSTR_Close'], returns['IBIT_Close'])[0, 1]
variance = np.var(returns['IBIT_Close'])

# Calculate beta: how MSTR's returns respond to IBIT's returns
beta = covariance / variance

print("Beta (MSTR relative to IBIT):", beta)
