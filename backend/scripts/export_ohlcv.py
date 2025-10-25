# backend/scripts/export_ohlcv.py
"""
Export OHLCV parquet backups for symbols/timeframes using your existing feature pipeline.

Usage:
  PYTHONPATH=./backend python backend/scripts/export_ohlcv.py --symbols BTC/USDT ETH/USDT GLD --timeframes 1h 1d
"""
import argparse
from pathlib import Path
import os
from dotenv import load_dotenv
import pandas as pd

# ensure ml package importable
ROOT = Path.cwd()
ML_PATH = ROOT / "backend" / "ml"
if str(ML_PATH) not in os.sys.path:
    os.sys.path.insert(0, str(ML_PATH))

try:
    from feature_pipeline import prepare_feature_matrix
except Exception as e:
    raise SystemExit("feature_pipeline import failed: " + str(e))

load_dotenv()
DATA_BACKUP = ROOT / "data_backup"
DATA_BACKUP.mkdir(parents=True, exist_ok=True)

def export_one(symbol, timeframe):
    print("Loading features for", symbol, timeframe)
    X, y, y_clf, df_full = prepare_feature_matrix(symbol=symbol, timeframe=timeframe, horizon=1)
    if df_full is None or df_full.empty:
        print("No df_full returned for", symbol, timeframe)
        return False
    # ensure df_full has ts, open, high, low, close, volume
    cols = ["ts","open","high","low","close","volume"]
    missing = [c for c in cols if c not in df_full.columns]
    if missing:
        print("df_full missing columns:", missing, " — trying to infer from X")
    # take only required columns
    out = df_full.copy()
    if "ts" in out.columns:
        out = out.sort_index().reset_index()
    else:
        out = out.reset_index().rename(columns={"index":"ts"})
    # ensure ts is datetime
    out["ts"] = pd.to_datetime(out["ts"])
    fn = DATA_BACKUP / f"{symbol.replace('/','_')}_{timeframe}.parquet"
    out.to_parquet(fn, index=False)
    print("Wrote", fn)
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["BTC/USDT","ETH/USDT","GLD","AAPL"])
    parser.add_argument("--timeframes", nargs="+", default=["1h","1d"])
    args = parser.parse_args()
    for tf in args.timeframes:
        for sym in args.symbols:
            try:
                export_one(sym, tf)
            except Exception as e:
                print("Failed exporting", sym, tf, e)
