import os
import time
from datetime import datetime
import ccxt
import pandas as pd
import sqlalchemy as sa
from dotenv import load_dotenv
from tqdm import tqdm
from sqlalchemy import text 


load_dotenv()

PG_URI = os.getenv("PG_URI")
SYMBOLS = [s.strip() for s in os.getenv("FETCH_SYMBOLS", "BTC/USDT,ETH/USDT").split(",")]
TIMEFRAME = os.getenv("TIMEFRAME", "1h")
START_SINCE = os.getenv("START_SINCE", "2021-01-01T00:00:00Z")

engine = sa.create_engine(PG_URI)

def create_table():
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

def fetch_ohlcv(symbol, since_iso, timeframe="1h"):
    exchange = ccxt.binance({"enableRateLimit": True})
    since_ms = int(pd.Timestamp(since_iso).timestamp() * 1000)
    all_data = []
    limit = 1000

    print(f"Fetching {symbol} data...")
    while True:
        candles = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)
        if not candles:
            break
        all_data += candles
        since_ms = candles[-1][0] + 1
        time.sleep(exchange.rateLimit / 1000)
        if len(candles) < limit:
            break

    df = pd.DataFrame(all_data, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df.drop(columns="ts_ms", inplace=True)
    df = df.drop_duplicates(subset="ts")
    return df



def save_to_db(symbol, df):
    """
    Robust bulk upsert:
    - Accepts df that either already has a 'ts' column or has a DatetimeIndex.
    - Writes a temp table and performs a single INSERT ... ON CONFLICT DO UPDATE.
    """
    if df is None or df.empty:
        print(f"No data for {symbol}")
        return

    # Ensure we don't modify original df
    df_work = df.copy()

    # If timestamp is in a column named 'ts', ensure correct dtype
    if "ts" in df_work.columns:
        # normalize tz-aware timestamp
        df_work["ts"] = pd.to_datetime(df_work["ts"], utc=True)
    else:
        # If there's a DatetimeIndex, reset it to a 'ts' column.
        # If index has a name other than None, use that name -> rename to ts.
        if isinstance(df_work.index, pd.DatetimeIndex):
            name = df_work.index.name if df_work.index.name else "ts"
            df_work = df_work.reset_index().rename(columns={name: "ts"})
            df_work["ts"] = pd.to_datetime(df_work["ts"], utc=True)
        else:
            # fallback: if neither column nor index contains ts, abort
            raise ValueError("DataFrame must have a 'ts' column or a DatetimeIndex")

    # Ensure we don't duplicate columns: drop any accidental extra 'index' column
    if "index" in df_work.columns and "ts" in df_work.columns and df_work["index"].equals(df_work["ts"]):
        df_work = df_work.drop(columns=["index"])

    # Prepare and order columns expected by DB
    expected_cols = ["symbol", "ts", "open", "high", "low", "close", "volume"]
    # Ensure open/high/low/close/volume exist (if not, create with NaNs)
    for c in ["open", "high", "low", "close", "volume"]:
        if c not in df_work.columns:
            df_work[c] = None

    df_work["symbol"] = symbol
    # reorder (some DBs don't like unexpected extra columns in SELECT)
    df_to_write = df_work[[c for c in expected_cols if c in df_work.columns]]

    temp_table = "ohlcv_temp_upload"

    try:
        # Write the temp table (replace existing temp)
        df_to_write.to_sql(temp_table, engine, if_exists="replace", index=False)

        # Upsert from temp -> main table
        with engine.begin() as conn:
            upsert_sql = text(f"""
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
            """)
            conn.execute(upsert_sql)
            conn.execute(text(f"DROP TABLE IF EXISTS {temp_table};"))

        print(f"Upserted {len(df_to_write)} rows for {symbol}")
    except Exception as e:
        # cleanup temp table in case of error
        try:
            with engine.begin() as conn:
                conn.execute(text(f"DROP TABLE IF EXISTS {temp_table};"))
        except Exception:
            pass
        # re-raise with context
        raise RuntimeError(f"Failed to upsert for {symbol}: {e}") from e



def save_to_parquet(symbol, df):
    folder = "data_backup"
    os.makedirs(folder, exist_ok=True)
    filename = f"{folder}/{symbol.replace('/','_')}_{TIMEFRAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
    df.to_parquet(filename)
    print(f"Saved local backup: {filename}")

def main():
    create_table()
    for symbol in SYMBOLS:
        df = fetch_ohlcv(symbol, START_SINCE, TIMEFRAME)
        save_to_db(symbol, df)
        save_to_parquet(symbol, df)
    print("✅ Ingestion complete!")

if __name__ == "__main__":
    main()
