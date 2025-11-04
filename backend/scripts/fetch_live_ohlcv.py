# backend/scripts/fetch_live_ohlcv.py
"""
Fetch live OHLCV for crypto (Binance via ccxt) and stocks/ETF (yfinance).
Writes CSVs with columns: timestamp,open,high,low,close,volume
Filenames: SYMBOL_TIMEFRAME.csv  (e.g. ETH_USDT_1h.csv, AAPL_1d.csv, GLD_1h.csv)
"""

import os
import time
from pathlib import Path
import argparse
import ccxt
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone

# defaults; change if needed
DEFAULT_DATA_DIR = os.getenv("DATA_DIR") or str(Path(__file__).resolve().parents[2] / "data")

# timeframe mapping for ccxt: e.g. "1h", "4h", "1d" -> "1h" etc.
# ccxt uses "1m","5m","15m","30m","1h","4h","1d", etc.
VALID_TFS = {"1m","5m","15m","30m","1h","4h","1d","1w"}

def ensure_data_dir(path):
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

def save_df_to_csv(df: pd.DataFrame, out_path: Path):
    # ensure standard columns and ISO timestamp
    # df expected with index as datetime or column 'timestamp'
    if 'timestamp' not in df.columns:
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index().rename(columns={'index':'timestamp'})
        elif 'Date' in df.columns:
            df = df.rename(columns={'Date':'timestamp'})
    # Force timestamp -> ISO without timezone
    df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_convert(None).dt.strftime("%Y-%m-%dT%H:%M:%S")
    # Only keep expected columns
    cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df = df[cols]
    df.to_csv(out_path, index=False)
    print(f"Wrote: {out_path}")

def fetch_crypto_ccxt(symbol: str, timeframe: str, limit: int = 500, data_dir: Path = None):
    # symbol e.g. "ETH/USDT"
    if timeframe not in VALID_TFS:
        raise ValueError("invalid timeframe")
    exchange = ccxt.binance({'enableRateLimit': True})
    # ccxt expects timeframe as "1h","4h" etc.
    print(f"Fetching {symbol} {timeframe} from Binance")
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    # ohlcv rows: [timestamp_ms, open, high, low, close, volume]
    df = pd.DataFrame(ohlcv, columns=['ts_ms','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['ts_ms'], unit='ms', utc=True)
    df = df.drop(columns=['ts_ms'])
    out_name = symbol.replace("/", "_") + "_" + timeframe + ".csv"
    out_path = data_dir / out_name
    save_df_to_csv(df, out_path)
    return out_path

def fetch_stock_yfinance(ticker: str, period: str, interval: str, out_symbol: str, timeframe: str, data_dir: Path):
    """
    ticker: e.g. "AAPL" or "GLD"
    period: e.g. "60d" or "730d"
    interval: "1d", "1h" (note: yfinance hourly may be limited)
    out_symbol: symbol to write filename (AAPL or GLD)
    timeframe: timeframe token for filename "1d" or "1h"
    """
    print(f"Fetching {ticker} via yfinance period={period}, interval={interval}")
    # yfinance returns timezone-aware DatetimeIndex
    df = yf.download(tickers=ticker, period=period, interval=interval, progress=False)
    if df.empty:
        print("yfinance returned empty for", ticker)
        return None
    # Reset index and rename Date -> timestamp
    df = df.reset_index().rename(columns={'Datetime':'timestamp', 'Date':'timestamp', 'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})
    # yfinance uses columns Open/High/Low/Close or lowercase depending; ensure synonyms
    for col in ['Open','High','Low','Close','Volume']:
        if col in df.columns:
            df.rename(columns={col: col.lower()}, inplace=True)
    # If timestamp has tz info, keep it then convert in save_df_to_csv
    out_name = out_symbol.replace("/", "_") + "_" + timeframe + ".csv"
    out_path = data_dir / out_name
    save_df_to_csv(df, out_path)
    return out_path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--symbols", nargs="+", default=["ETH/USDT","BTC/USDT","AAPL","GLD"])
    parser.add_argument("--timeframe", default="1h", help="1m,5m,15m,30m,1h,4h,1d")
    parser.add_argument("--rows", type=int, default=500)
    args = parser.parse_args()

    data_dir = ensure_data_dir(Path(args.data_dir))

    for s in args.symbols:
        try:
            if "/" in s:  # crypto pair
                # Binance uses uppercase like ETH/USDT
                fetch_crypto_ccxt(s.upper(), args.timeframe, limit=args.rows, data_dir=data_dir)
                time.sleep(0.5)
            else:
                # stock/ETF: use yfinance.
                # map timeframe: for 1d use period 2y; for 1h use 60d with interval 1h.
                if args.timeframe == "1d":
                    period = "730d"
                    interval = "1d"
                elif args.timeframe == "1h":
                    period = "60d"
                    interval = "1h"
                else:
                    period = "180d"
                    interval = args.timeframe
                fetch_stock_yfinance(s.upper(), period=period, interval=interval, out_symbol=s.upper(), timeframe=args.timeframe, data_dir=data_dir)
                time.sleep(0.5)
        except Exception as e:
            print("Failed to fetch", s, e)

if __name__ == "__main__":
    main()
