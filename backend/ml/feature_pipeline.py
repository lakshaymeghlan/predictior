import os
from datetime import timezone
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
from tqdm import tqdm

load_dotenv()

PG_URI = os.getenv("PG_URI")
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
TIMEFRAME = os.getenv("TIMEFRAME", "1h")
HOURS_LOOKBACK = int(os.getenv("HOURS_LOOKBACK", "72"))

engine = create_engine(PG_URI)


def load_ohlcv_from_db(symbol: str):
    """
    Load OHLCV for symbol from Postgres and return a DataFrame indexed by tz-aware UTC DatetimeIndex.
    """
    query = text("""
        SELECT ts AT TIME ZONE 'UTC' AS ts, open, high, low, close, volume
        FROM ohlcv
        WHERE symbol = :symbol
        ORDER BY ts ASC
    """)
    df = pd.read_sql(query, engine, params={"symbol": symbol}, parse_dates=["ts"])

    # If no rows, return empty df with expected columns
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]).astype(float)

    # Ensure 'ts' column exists and is parsed as datetimetz (UTC)
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        # Set as index (DatetimeIndex)
        df = df.set_index("ts")
    else:
        # If 'ts' not present, try to coerce the existing index to datetime
        df.index = pd.to_datetime(df.index, utc=True)

    # Ensure index is tz-aware UTC (defensive)
    if getattr(df.index, "tz", None) is None:
        df.index = df.index.tz_localize("UTC")

    # Sort by index just in case
    df = df.sort_index()

    return df



def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # basic returns
    df["return_1h"] = df["close"].pct_change()
    df["return_3h"] = df["close"].pct_change(3)
    df["return_24h"] = df["close"].pct_change(24)

    # log returns
    df["logret_1h"] = np.log(df["close"] / df["close"].shift(1))

    # EMA features
    for span in [8, 21, 50]:
        df[f"ema_{span}"] = EMAIndicator(close=df["close"], window=span).ema_indicator()

    # RSI
    df["rsi_14"] = RSIIndicator(close=df["close"], window=14).rsi()

    # ATR (volatility)
    df["atr_14"] = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()

    # rolling stats
    df["vol_24h"] = df["return_1h"].rolling(24).std()
    df["vol_72h"] = df["return_1h"].rolling(72).std()

    # volume features
    df["vol_zscore_24"] = (df["volume"] - df["volume"].rolling(24).mean()) / (df["volume"].rolling(24).std() + 1e-9)

    # time features
    df["hour"] = df.index.hour
    df["dow"] = df.index.dayofweek

    # momentum cross features
    df["ema8_minus_ema21"] = df["ema_8"] - df["ema_21"]
    df["ema8_div_ema21"] = df["ema_8"] / (df["ema_21"] + 1e-9)

    # Fill/clean
    df = df.dropna().copy()
    return df


def build_target(df: pd.DataFrame, horizon: int = 1):
    """
    Create next-hour return target (shifted -horizon)
    and binary label up_1h (1 if return > 0 else 0)
    """
    df = df.copy()
    df[f"next_{horizon}h_return"] = df["close"].shift(-horizon) / df["close"] - 1.0
    df = df.dropna().copy()
    df[f"up_{horizon}h"] = (df[f"next_{horizon}h_return"] > 0).astype(int)
    return df


def prepare_feature_matrix(symbol: str = SYMBOL, horizon: int = 1):
    df = load_ohlcv_from_db(symbol)
    if df.empty:
        raise RuntimeError("No OHLCV data found for symbol: " + symbol)
    df_feat = compute_features(df)
    df_target = build_target(df_feat, horizon=horizon)
    # choose feature columns (exclude raw price & next return)
    exclude = ["open", "high", "low", "close", "volume", f"next_{horizon}h_return", f"up_{horizon}h"]
    feature_cols = [c for c in df_target.columns if c not in exclude]
    X = df_target[feature_cols].copy()
    y = df_target[f"next_{horizon}h_return"].copy()
    y_clf = df_target[f"up_{horizon}h"].copy()
    return X, y, y_clf, df_target


if __name__ == "__main__":
    X, y, y_clf, df_full = prepare_feature_matrix()
    print("Prepared features:", X.shape)
    print("Example columns:", X.columns.tolist()[:20])
