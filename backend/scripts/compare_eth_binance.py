# backend/scripts/compare_eth_binance.py
import ccxt, pandas as pd
from pathlib import Path
import datetime as dt

DATA_FILE = Path("E:/predictior/predictior/data/ETH_USDT_1h.csv")   # adjust if required

def load_csv():
    df = pd.read_csv(DATA_FILE, parse_dates=["timestamp"])
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df.set_index('timestamp', inplace=True)
    return df

def fetch_binance(symbol="ETH/USDT", timeframe="1h", since=None, limit=100):
    ex = ccxt.binance({'enableRateLimit': True})
    # since in ms; if None ccxt will return latest `limit`
    raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
    df = pd.DataFrame(raw, columns=['ts_ms','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['ts_ms'], unit='ms', utc=True)
    df.set_index('timestamp', inplace=True)
    df = df[['open','high','low','close','volume']]
    return df

def compare():
    csv = load_csv()
    # compare the last N rows
    last_ts = csv.index[-10]
    since_ms = int(last_ts.timestamp()*1000) - 24*3600*1000  # fetch from 24h before last row
    binance = fetch_binance(since=since_ms, limit=200)
    # align by index nearest
    joined = csv.join(binance, lsuffix='_csv', rsuffix='_bin', how='inner')
    print("Joined rows:", len(joined))
    if joined.empty:
        print("No overlapping rows; printing tails:")
        print("CSV tail:")
        print(csv.tail(5))
        print("Binance tail:")
        print(binance.tail(5))
        return
    # show differences for last 5 rows
    print(joined.tail(10)[[
        'open_csv','open_bin','close_csv','close_bin','volume_csv','volume_bin'
    ]])
    # show percent diff for close
    joined['close_pct_diff'] = (joined['close_csv'] - joined['close_bin']) / joined['close_bin'] * 100.0
    print("Close % diff (tail):")
    print(joined['close_pct_diff'].tail(10))

if __name__ == "__main__":
    compare()
