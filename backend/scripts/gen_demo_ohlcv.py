# backend/scripts/gen_demo_ohlcv.py
"""
Generate synthetic OHLCV CSV files for demo:
BTC_USDT_1h.csv, ETH_USDT_1h.csv, GLD_1h.csv, AAPL_1d.csv
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

OUT = Path(__file__).resolve().parents[2] / "data"
OUT.mkdir(parents=True, exist_ok=True)

def make_series(start_price=1000, n=500, freq="H", vol=0.01):
    rng = pd.date_range(end=datetime.utcnow(), periods=n, freq=freq)
    # geometric random walk
    returns = np.random.normal(loc=0.0001, scale=vol, size=n)
    price = start_price * np.exp(np.cumsum(returns))
    df = pd.DataFrame({"timestamp": rng, "close": price})
    df["open"] = df["close"].shift(1).fillna(df["close"])
    df["high"] = np.maximum(df["open"], df["close"]) * (1 + np.random.rand(n)*0.005)
    df["low"] = np.minimum(df["open"], df["close"]) * (1 - np.random.rand(n)*0.005)
    df["volume"] = (np.random.rand(n) * 1000).astype(int)
    df = df[["timestamp","open","high","low","close","volume"]]
    return df

datasets = [
    ("BTC_USDT_1h.csv", 25000, "H", 0.02),
    ("ETH_USDT_1h.csv", 1600, "H", 0.025),
    ("GLD_1h.csv", 190, "H", 0.005),
    ("AAPL_1d.csv", 150, "D", 0.02),
]

for fname, start, freq, vol in datasets:
    df = make_series(start_price=start, n=500, freq=freq, vol=vol)
    p = OUT / fname
    df.to_csv(p, index=False)
    print("Wrote:", p)
