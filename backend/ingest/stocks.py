# backend/ingest/stocks.py
"""
Ingest daily OHLCV for stocks/ETFs (yfinance) and upsert into ohlcv Postgres/Timescale table.

Usage:
  python backend/ingest/stocks.py --symbols AAPL,GLD --start 2010-01-01
"""
import argparse
from pathlib import Path
import os
from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import create_engine, text

load_dotenv()
PG_URI = os.getenv("PG_URI")
if not PG_URI:
    raise RuntimeError("PG_URI not set in .env")

engine = create_engine(PG_URI, echo=False)

def upsert_df_to_ohlcv(symbol: str, df: pd.DataFrame):
    """
    df must have columns: ts (datetime tz-aware UTC), open, high, low, close, volume
    """
    temp_table = "ohlcv_temp_upload"
    df2 = df.copy()
    df2["symbol"] = symbol
    # pandas -> temp table
    df2.to_sql(temp_table, engine, if_exists="replace", index=False)
    # upsert using SQL
    with engine.begin() as conn:
        conn.execute(text(f"""
            INSERT INTO ohlcv (symbol, ts, open, high, low, close, volume)
            SELECT symbol, ts::timestamptz, open, high, low, close, volume
            FROM {temp_table}
            ON CONFLICT (symbol, ts)
            DO UPDATE SET
              open = EXCLUDED.open,
              high = EXCLUDED.high,
              low = EXCLUDED.low,
              close = EXCLUDED.close,
              volume = EXCLUDED.volume;
        """))
        conn.execute(text(f"DROP TABLE IF EXISTS {temp_table};"))

def fetch_and_ingest(symbol: str, start="2010-01-01"):
    import yfinance as yf
    tk = yf.Ticker(symbol)
    df = tk.history(start=start, interval="1d", actions=False, auto_adjust=False)
    if df.empty:
        print(f"No data for {symbol}")
        return
    df = df.reset_index().rename(columns={"Date": "ts", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    # ensure tz aware UTC
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df[["ts", "open", "high", "low", "close", "volume"]]
    upsert_df_to_ohlcv(symbol, df)
    print(f"Ingested {len(df)} rows for {symbol}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="AAPL,GLD", help="Comma separated tickers")
    parser.add_argument("--start", default="2010-01-01")
    args = parser.parse_args()
    syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
    for s in syms:
        fetch_and_ingest(s, start=args.start)
