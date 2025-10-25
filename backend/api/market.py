# backend/api/market.py
from fastapi import APIRouter, HTTPException, Query, Response
from pathlib import Path
import os, pandas as pd, json

from fastapi.responses import FileResponse

router = APIRouter(prefix="/market")

# Possible data dirs to check (backend runs from backend/ folder)
repo_root = Path(__file__).resolve().parents[2]
candidate_dirs = [
    Path(os.getenv("DATA_DIR", repo_root / "data")),   # env override or repo_root/data
    repo_root / "data",                                # backend/data (if run from repo root)
    repo_root.parent / "data"                          # repo_root/../data (older default)
]
# de-dup, ensure exists
DATA_DIRS = [p.resolve() for p in dict.fromkeys(candidate_dirs) if p.exists()]

def find_file_for(symbol: str, timeframe: str):
    # symbol like "BTC/USDT" -> file prefix "BTC_USDT"
    key = symbol.replace("/", "_")
    names = [f"{key}_{timeframe}.parquet", f"{key}_{timeframe}.csv", f"{key}.csv"]
    for d in DATA_DIRS:
        for n in names:
            p = d / n
            if p.exists():
                return p
    return None

@router.get("/symbols")
def list_symbols():
    # scan data dirs for files and expose symbol list
    seen = {}
    for d in DATA_DIRS:
        for f in d.glob("*"):
            if f.suffix.lower() in [".csv", ".parquet"]:
                name = f.stem  # e.g. BTC_USDT_1h
                # try to parse into symbol/timeframe
                parts = name.split("_")
                # normalize symbol display
                if len(parts) >= 3 and parts[-1] in ("1h","4h","1d","1m","5m","15m"):
                    sym = "_".join(parts[:-1]).replace("_", "/")
                    tf = parts[-1]
                elif len(parts) >= 2:
                    sym = parts[0] + "/" + parts[1]
                    tf = None
                else:
                    sym = name.replace("_", "/")
                    tf = None

                key = f"{sym}" if tf is None else f"{sym}:{tf}"
                seen[key] = {
                    "symbol": sym,
                    "timeframe": tf,
                    "file": str(f.name),
                    "path": str(f)
                }
    # include candidate dirs even if empty so frontend can show them
    return {"data_dir_candidates": [str(x) for x in DATA_DIRS], "symbols": list(seen.values())}

@router.get("/ohlcv")
def ohlcv_history(symbol: str = Query(...), timeframe: str = Query("1h"), rows: int = Query(500)):
    p = find_file_for(symbol, timeframe)
    if p is None:
        # helpful message with dirs checked
        dirs = ", ".join(str(x) for x in DATA_DIRS) or str(Path(os.getenv("DATA_DIR", repo_root / "data")).resolve())
        raise HTTPException(status_code=404, detail=f"No OHLCV data for {symbol} {timeframe}. Provide {symbol.replace('/','_')}_{timeframe}.parquet or .csv in one of: {dirs}")
    try:
        if p.suffix.lower() == ".parquet":
            df = pd.read_parquet(p)
        else:
            # read CSV; try to detect timestamp column
            sample = pd.read_csv(p, nrows=2)
            ts_col = "timestamp" if "timestamp" in sample.columns else ("time" if "time" in sample.columns else sample.columns[0])
            df = pd.read_csv(p, parse_dates=[ts_col])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unable to read {p.name}: {e}")

    # ensure timestamp column exists and is sorted
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp").tail(rows)
    elif "time" in df.columns:
        df = df.sort_values("time").tail(rows).rename(columns={"time": "timestamp"})
    else:
        # fallback: assume first column is timestamp-like
        df = df.tail(rows).reset_index()
        df.rename(columns={df.columns[0]: "timestamp"}, inplace=True)

    # normalize expected columns: timestamp, open, high, low, close, volume
    expected = ["timestamp", "open", "high", "low", "close", "volume"]
    for col in expected:
        if col not in df.columns:
            df[col] = None

    out = df.tail(rows).to_dict(orient="records")
    # convert timestamps to ISO strings
    for r in out:
        if r.get("timestamp") is not None:
            try:
                r["timestamp"] = pd.to_datetime(r["timestamp"]).isoformat()
            except Exception:
                r["timestamp"] = str(r["timestamp"])
    return {"symbol": symbol, "timeframe": timeframe, "rows": len(out), "data": out}

@router.get("/backtest/latest")
def backtest_latest(symbol: str = Query(None)):
    # serve PNG from models/backtests if present
    models_dir = Path(os.getenv("MODEL_DIR", Path(__file__).resolve().parents[2] / "models")).resolve()
    backtests_dir = models_dir / "backtests"
    backtests = sorted(backtests_dir.glob("equity_*.png") if backtests_dir.exists() else [], key=lambda p: p.stat().st_mtime, reverse=True)
    if backtests:
        # return filename; frontend can call /market/backtest/raw to fetch it
        return {"file": backtests[0].name}
    raise HTTPException(status_code=404, detail="No backtest image found")


@router.get("/backtest/raw")
def backtest_raw(file: str = Query(...)):
    models_dir = Path(os.getenv("MODEL_DIR", Path(__file__).resolve().parents[2] / "models")).resolve()
    p = models_dir / "backtests" / file
    if not p.exists():
        raise HTTPException(status_code=404, detail="file missing")
    return FileResponse(path=str(p), media_type="image/png", filename=p.name)
