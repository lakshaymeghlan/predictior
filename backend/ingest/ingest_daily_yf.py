# predictor/backend/ingest/ingest_daily_yf.py
"""
Fetch daily OHLCV for a list of tickers (stocks / ETFs / commodities via yfinance)
and upsert into the same ohlcv table (symbol, ts ...). Uses pandas.to_sql with temp table + upsert.

Usage:
    PYTHONPATH=.. python ingest_daily_yf.py
"""
import os
from pathlib import Path
from datetime import datetime
import pandas as pd
import yfinance as yf
import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy import text
from tqdm import tqdm

load_dotenv()

PG_URI = os.getenv("PG_URI")  # same connection used earlier
SYMBOLS = [s.strip() for s in os.getenv("DAILY_SYMBOLS", "AAPL,SPY,GLD").split(",")]
START_SINCE = os.getenv("START_SINCE", "2010-01-01")
MODEL_DIR = Path(os.getenv("MODEL_DIR","../models")).resolve()

if PG_URI is None:
    raise RuntimeError("PG_URI not found in .env")

engine = sa.create_engine(PG_URI)

def create_ohlcv_table():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ohlcv (
                symbol TEXT NOT NULL,
                ts TIMESTAMPTZ NOT NULL,
                open DOUBLE PRECISION,
                high DOUBLE PRECISION,
                low DOUBLE PRECISION,
                close DOUBLE PRECISION,
                volume DOUBLE PRECISION,
                PRIMARY KEY (symbol, ts)
            );
        """))

def fetch_yf(symbol, start):
    # Normalize start to 'YYYY-MM-DD' string that yfinance accepts
    if isinstance(start, str):
        try:
            start_dt = pd.to_datetime(start)
            start = start_dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    print("Fetching", symbol, "since", start)
    t = yf.Ticker(symbol)
    df = t.history(start=start, interval="1d", auto_adjust=False)
    if df is None or df.empty:
        return None

    # select and rename OHLCV columns
    df = df[["Open", "High", "Low", "Close", "Volume"]].rename(columns={
        "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"
    })

    # reset index -> ensures the timestamp becomes a column
    df = df.reset_index()

    # Find which column is the datetime column (could be 'index', 'Date', etc.)
    datetime_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    if len(datetime_cols) == 0:
        # try to coerce the first column to datetime (fallback)
        first_col = df.columns[0]
        try:
            df[first_col] = pd.to_datetime(df[first_col])
            datetime_col = first_col
        except Exception:
            raise RuntimeError("Could not find or convert a datetime column in yfinance result for " + symbol)
    else:
        datetime_col = datetime_cols[0]

    # Normalize to 'ts' and ensure UTC tz
    df = df.rename(columns={datetime_col: "ts"})
    df["ts"] = pd.to_datetime(df["ts"])
    if df["ts"].dt.tz is None:
        df["ts"] = df["ts"].dt.tz_localize("UTC")
    else:
        df["ts"] = df["ts"].dt.tz_convert("UTC")

    df["symbol"] = symbol

    # Ensure column order and existence before returning
    expected_cols = ["symbol", "ts", "open", "high", "low", "close", "volume"]
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"Missing columns after fetch for {symbol}: {missing}")

    return df[expected_cols]


def upsert_df(df):
    # write temp table then upsert
    temp_table = "ohlcv_temp_upload"
    df.to_sql(temp_table, engine, if_exists="replace", index=False)
    with engine.begin() as conn:
        conn.execute(text(f"""
            INSERT INTO ohlcv (symbol, ts, open, high, low, close, volume)
            SELECT symbol, ts::timestamptz, open, high, low, close, volume
            FROM {temp_table}
            ON CONFLICT (symbol, ts)
            DO UPDATE SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume;
        """))
        conn.execute(text(f"DROP TABLE IF EXISTS {temp_table};"))

def main():
    create_ohlcv_table()
    for sym in SYMBOLS:
        df = fetch_yf(sym, START_SINCE)
        if df is None or df.empty:
            print("No data for", sym)
            continue
        upsert_df(df)
        # save local backup
        bkp = MODEL_DIR / "data_backup"
        bkp.mkdir(parents=True, exist_ok=True)
        fn = bkp / f"{sym}_1d_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.parquet"
        df.to_parquet(str(fn))
        print("Saved", fn)

if __name__ == "__main__":
    main()
