import ccxt
import pandas as pd
import numpy as np
import os
from dotenv import load_dotenv

load_dotenv()

def analyze_current_zscore():
    exchange = ccxt.binanceusdm({
        'options': {'adjustForTimeDifference': True}
    })
    
    symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT']
    data = {}
    
    print("正在获取市场数据...")
    for symbol in symbols:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='30m', limit=50)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        data[symbol] = df['close']

    s1 = data[symbols[0]]
    s2 = data[symbols[1]]
    ratio = s1 / s2
    
    window = 20
    mean = ratio.rolling(window=window).mean()
    std = ratio.rolling(window=window).std()
    zscore = (ratio - mean) / std
    
    current_ratio = ratio.iloc[-1]
    current_zscore = zscore.iloc[-1]
    last_5_zscores = zscore.tail(5).tolist()
    
    print(f"\n当前价格比率 (BTC/ETH): {current_ratio:.4f}")
    print(f"当前 Z-Score: {current_zscore:.4f}")
    print(f"最近 5 个周期 Z-Score: {[round(z, 4) for z in last_5_zscores]}")
    
    if abs(current_zscore) >= 2:
        print("状态: 已达到入场阈值!")
    elif abs(current_zscore) >= 1.5:
        print("状态: 接近入场点 (临界值 2.0)")
    else:
        print("状态: 波动较小，需等待比率偏离均值")

if __name__ == "__main__":
    analyze_current_zscore()
