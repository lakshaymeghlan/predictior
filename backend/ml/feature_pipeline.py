# predictor/backend/ml/feature_pipeline.py
"""
Feature pipeline: load OHLCV from DB, resample to timeframe, compute rolling indicators.

Exposes:
    prepare_feature_matrix(symbol='BTC/USDT', timeframe='1h', horizon=1)
Returns:
    X (DataFrame of features), y (continuous return), y_clf (binary up/down), df_full (OHLCV with returns)
"""
import os
import pandas as pd
import numpy as np
import sqlalchemy as sa
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()
PG_URI = os.getenv("PG_URI")
if PG_URI is None:
    raise RuntimeError("PG_URI environment not set. Add PG_URI to .env")

engine = sa.create_engine(PG_URI, future=True)

def load_ohlcv_from_db(symbol):
    q = sa.text("SELECT symbol, ts AT TIME ZONE 'UTC' as ts, open, high, low, close, volume FROM ohlcv WHERE symbol = :sym ORDER BY ts ASC")
    df = pd.read_sql(q, engine, params={"sym": symbol})
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()
    return df

def resample_ohlcv(df, timeframe):
    """
    timeframe: examples '1h', '4h', '1d'
    """
    if timeframe == "1h":
        return df
    if timeframe.endswith("h"):
        hours = int(timeframe[:-1])
        rule = f"{hours}H"
        agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }
        return df.resample(rule).agg(agg).dropna()
    if timeframe in ("1d","daily","24h"):
        agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }
        return df.resample("1D").agg(agg).dropna()
    # default: return original
    return df

def add_technical_indicators(df):
    # computes a set of rolling indicators
    df = df.copy()
    close = df["close"]
    df["ret_1"] = close.pct_change().fillna(0)
    df["ret_3"] = close.pct_change(3)
    df["ret_24"] = close.pct_change(24) if len(df) > 24 else close.pct_change().fillna(0)
    # EMAs
    df["ema_8"] = close.ewm(span=8, adjust=False).mean()
    df["ema_21"] = close.ewm(span=21, adjust=False).mean()
    df["ema_50"] = close.ewm(span=50, adjust=False).mean()
    # RSI (14)
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    roll_up = up.rolling(14).mean()
    roll_down = down.rolling(14).mean()
    rs = roll_up / (roll_down + 1e-9)
    df["rsi_14"] = 100 - (100 / (1 + rs))
    # volatility / ATR
    df["hl_range"] = (df["high"] - df["low"]) / df["close"]
    df["vol_21"] = df["ret_1"].rolling(21).std()
    # momentum indicator
    df["momentum_12"] = close.pct_change(12)
    # moving average cross features
    df["ema8_ema21"] = df["ema_8"] - df["ema_21"]
    df = df.replace([np.inf, -np.inf], np.nan)
    return df

def prepare_feature_matrix(symbol="BTC/USDT", timeframe="1h", horizon=1):
    """
    Prepares X, y for a symbol/timeframe/horizon:
      - X: features up to time t
      - y: forward return over horizon (close_{t+h}/close_t - 1)
      - y_clf: binary up/down label
    """
    df = load_ohlcv_from_db(symbol)
    if df.empty:
        return pd.DataFrame(), pd.Series(dtype=float), pd.Series(dtype=int), df

    df = resample_ohlcv(df, timeframe)
    if df.empty or len(df) < 200:
        return pd.DataFrame(), pd.Series(dtype=float), pd.Series(dtype=int), df

    df = add_technical_indicators(df)
    # forward return
    df["future_close"] = df["close"].shift(-horizon)
    df["target_ret"] = df["future_close"] / df["close"] - 1
    df["target_up"] = (df["target_ret"] > 0).astype(int)

    # features list (drop columns we don't want)
    drop_cols = ["future_close","target_ret","target_up"]
    features = [c for c in df.columns if c not in drop_cols and c not in ["symbol"]]
    X = df[features].copy().dropna()
    y = df.loc[X.index, "target_ret"].copy()
    y_clf = df.loc[X.index, "target_up"].copy()

    return X, y, y_clf, df
