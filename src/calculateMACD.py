import pandas as pd
import numpy as np


def calculate_macd(df, price_col='close', fastperiod=12, slowperiod=26, signalperiod=9):
    ewma12 = df[price_col].ewm(span=fastperiod, adjust=False).mean()
    ewma26 = df[price_col].ewm(span=slowperiod, adjust=False).mean()
    df['dif'] = ewma12 - ewma26
    df['dea'] = df['dif'].ewm(span=signalperiod, adjust=False).mean()
    df['bar'] = (df['dif'] - df['dea']) * 2

    return df

# 示例用法
# data = pd.read_csv('stock_prices.csv')
# result = calculate_macd(data)