# backend/api/market.py
from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
import os
import pandas as pd
import json
from fastapi.responses import FileResponse
from datetime import datetime, timedelta, timezone
import time
from typing import Optional

# Optional libraries
try:
    import ccxt
except Exception:
    ccxt = None

try:
    import requests
except Exception:
    requests = None

router = APIRouter(prefix="/market")

TIMEFRAMES = ("1h", "4h", "1d", "1m", "5m", "15m")

# ----------------- small in-process cache to avoid repeated external calls -----------------
_SIMPLE_CACHE = {}
def _cache_get(key):
    ent = _SIMPLE_CACHE.get(key)
    if not ent:
        return None
    ts, ttl, val = ent
    if time.time() - ts > ttl:
        _SIMPLE_CACHE.pop(key, None)
        return None
    return val

def _cache_set(key, val, ttl=15):
    _SIMPLE_CACHE[key] = (time.time(), ttl, val)

# ----------------- helpers -----------------
def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]

def resolve_data_dirs():
    repo_root = get_repo_root()
    env_dir = os.getenv("DATA_DIR")
    candidate_dirs = [
        Path(env_dir) if env_dir else None,
        repo_root / "data",
        repo_root.parent / "data",
    ]
    seen = set()
    out = []
    for c in candidate_dirs:
        if c is None:
            continue
        try:
            r = Path(c).resolve()
        except Exception:
            r = Path(c)
        if str(r) in seen:
            continue
        seen.add(str(r))
        if r.exists():
            out.append(r)
    if not out:
        fallback = repo_root / "data"
        return [fallback.resolve()]
    return out

def find_file_for(symbol: str, timeframe: str):
    if not symbol:
        return None
    symbol = symbol.strip()
    timeframe = (timeframe or "1h").strip()
    if ("/" in symbol or "_" in symbol) and symbol.replace("_", "/").split("/")[-1] in TIMEFRAMES:
        parts = symbol.replace("_", "/").split("/")
        if parts and parts[-1] in TIMEFRAMES:
            timeframe = parts[-1]
            symbol = "/".join(parts[:-1]) or symbol

    key = symbol.replace("/", "_")
    candidates = [
        f"{key}_{timeframe}.parquet",
        f"{key}_{timeframe}.csv",
        f"{key}.parquet",
        f"{key}.csv",
    ]

    for d in resolve_data_dirs():
        for n in candidates:
            p = d / n
            if p.exists():
                return p
    return None

# ----------------- live fetch logic (ccxt first, then Binance REST fallback) -----------------
def _try_ccxt_fetch(symbol: str, timeframe: str, limit: int):
    if ccxt is None:
        raise RuntimeError("ccxt not available")
    exchange_id = os.getenv("EXCHANGE", "binance")
    if not hasattr(ccxt, exchange_id):
        raise RuntimeError(f"ccxt does not have exchange '{exchange_id}'")
    ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    try:
        return ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception as e:
        # try alternative format (no slash)
        try:
            alt = symbol.replace("/", "")
            return ex.fetch_ohlcv(alt, timeframe=timeframe, limit=limit)
        except Exception:
            raise RuntimeError(f"ccxt fetch failed for {symbol}: {e}")

def _try_binance_rest(symbol: str, timeframe: str, limit: int):
    # requires requests
    if requests is None:
        raise RuntimeError("requests not available for Binance REST fallback")
    endpoint = "https://api.binance.com/api/v3/klines"
    # Binance timeframe mapping is the same as our timeframe (1h,4h,1d etc)
    # try both symbol formats
    candidates = [symbol.replace("/", ""), symbol]
    last_err = None
    for cand in candidates:
        params = {"symbol": cand, "interval": timeframe, "limit": str(limit)}
        try:
            r = requests.get(endpoint, params=params, timeout=10)
            if r.status_code != 200:
                last_err = f"{r.status_code} {r.text}"
                continue
            arr = r.json()
            # each kline: [openTime, open, high, low, close, volume, closeTime, ...]
            # convert to our list-of-lists format matching ccxt
            out = []
            for k in arr:
                ts = int(k[0])
                open_p = float(k[1])
                high = float(k[2])
                low = float(k[3])
                close = float(k[4])
                vol = float(k[5])
                out.append([ts, open_p, high, low, close, vol])
            return out
        except Exception as e:
            last_err = str(e)
            continue
    raise RuntimeError(f"Binance REST fallback failed: {last_err}")

def fetch_live_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 500):
    """
    Unified live fetch. Returns pandas DataFrame with timestamp (UTC), open,high,low,close,volume
    """
    key = f"live::{symbol}::{timeframe}::{limit}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    # try ccxt
    last_exc = None
    try:
        raw = _try_ccxt_fetch(symbol, timeframe, limit)
    except Exception as e:
        last_exc = e
        raw = None

    # try REST fallback if ccxt failed
    if raw is None:
        try:
            raw = _try_binance_rest(symbol, timeframe, limit)
        except Exception as e2:
            # bubble combined error
            raise RuntimeError(f"Live fetch failed (ccxt: {last_exc}; rest: {e2})")

    # Normalize to DataFrame
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    # ccxt returns ms timestamps; our rest returns ms too (from Binance)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    _cache_set(key, df, ttl=12)  # small cache
    return df

# ----------------- endpoints -----------------
@router.get("/symbols")
def list_symbols():
    dirs = resolve_data_dirs()
    seen = {}
    for d in dirs:
        try:
            for f in d.glob("*"):
                if f.suffix.lower() not in (".csv", ".parquet"):
                    continue
                name = f.stem
                parts = name.split("_")
                if len(parts) >= 2 and parts[-1] in TIMEFRAMES:
                    tf = parts[-1]
                    sym_parts = parts[:-1]
                    sym = "/".join(sym_parts)
                elif len(parts) >= 2:
                    tf = None
                    sym = parts[0] + "/" + parts[1]
                else:
                    tf = None
                    sym = name.replace("_", "/")
                key = f"{sym}:{tf}" if tf else sym
                seen[key] = {
                    "symbol": sym,
                    "timeframe": tf,
                    "file": str(f.name),
                    "path": str(f.resolve()),
                }
        except Exception:
            continue
    return {"data_dir_candidates": [str(x) for x in dirs], "symbols": list(seen.values())}

@router.get("/ohlcv")
def ohlcv_history(symbol: str = Query(...), timeframe: str = Query("1h"), rows: int = Query(500)):
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol required")
    if ("/" in symbol or "_" in symbol) and symbol.replace("_", "/").split("/")[-1] in TIMEFRAMES:
        parts = symbol.replace("_", "/").split("/")
        if parts and parts[-1] in TIMEFRAMES:
            timeframe = parts[-1]
            symbol = "/".join(parts[:-1]) or symbol

    p = find_file_for(symbol, timeframe)
    live_needed = True
    if p and p.exists():
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if datetime.now(timezone.utc) - mtime < timedelta(hours=2):
                live_needed = False
        except Exception:
            live_needed = True

    if live_needed:
        try:
            df = fetch_live_ohlcv(symbol, timeframe, limit=rows)
            df = df.sort_values("timestamp").tail(rows)
            out = df.to_dict(orient="records")
            for r in out:
                r["timestamp"] = pd.to_datetime(r["timestamp"]).isoformat()
            return {"symbol": symbol, "timeframe": timeframe, "rows": len(out), "data": out}
        except Exception as e:
            # if live fails and file exists, fall back to file; otherwise error
            if not (p and p.exists()):
                dirs = ", ".join(str(x) for x in resolve_data_dirs())
                raise HTTPException(status_code=404, detail=f"No OHLCV file for {symbol} {timeframe}. Tried data dirs: {dirs}. Live fetch failed: {e}")
            # otherwise we will read stale file below

    # read from file if exists
    if not (p and p.exists()):
        raise HTTPException(status_code=404, detail=f"No OHLCV file found for {symbol} {timeframe}")

    try:
        if p.suffix.lower() == ".parquet":
            df = pd.read_parquet(p)
        else:
            sample = pd.read_csv(p, nrows=2)
            ts_col = None
            if "timestamp" in sample.columns:
                ts_col = "timestamp"
            elif "time" in sample.columns:
                ts_col = "time"
            else:
                ts_col = sample.columns[0]
            df = pd.read_csv(p, parse_dates=[ts_col])
            if ts_col != "timestamp":
                df.rename(columns={ts_col: "timestamp"}, inplace=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unable to read {p.name}: {e}")

    df = df.sort_values("timestamp").tail(rows)
    expected = ["timestamp", "open", "high", "low", "close", "volume"]
    for col in expected:
        if col not in df.columns:
            df[col] = None

    out = df.tail(rows).to_dict(orient="records")
    for r in out:
        if r.get("timestamp") is not None:
            try:
                r["timestamp"] = pd.to_datetime(r["timestamp"]).isoformat()
            except Exception:
                r["timestamp"] = str(r["timestamp"])
    return {"symbol": symbol, "timeframe": timeframe, "rows": len(out), "data": out}

@router.get("/live_summary")
def live_summary():
    """
    Return brief live data for a small set of tracked symbols (symbol, timeframe, last_close, change_pct, up, error?)
    """
    tracked = [
        ("BTC/USDT", "1h"),
        ("ETH/USDT", "1h"),
        ("SOL/USDT", "1h"),
        ("BNB/USDT", "1h"),
        ("AAPL", "1d"),
    ]
    results = []
    for sym, tf in tracked:
        try:
            # small per-symbol cache
            key = f"summary::{sym}::{tf}"
            cached = _cache_get(key)
            if cached is not None:
                results.append(cached)
                continue

            # fetch last 3 candles
            df = fetch_live_ohlcv(sym, tf, limit=3)
            df = df.sort_values("timestamp")
            if df.shape[0] < 2:
                entry = {"symbol": sym, "timeframe": tf, "error": "not enough candles"}
                results.append(entry)
                _cache_set(key, entry, ttl=12)
                continue
            last = df.iloc[-1]
            prev = df.iloc[-2]
            diff = float(last.close) - float(prev.close)
            pct = (diff / float(prev.close) * 100.0) if float(prev.close) else 0.0
            entry = {"symbol": sym, "timeframe": tf, "last_close": float(last.close), "change_pct": float(pct), "up": diff > 0}
            results.append(entry)
            _cache_set(key, entry, ttl=12)
        except Exception as e:
            results.append({"symbol": sym, "timeframe": tf, "error": str(e)})
    return {"data": results, "ts": datetime.utcnow().isoformat()}

@router.get("/backtest/latest")
def backtest_latest(symbol: str = Query(None)):
    models_dir = Path(os.getenv("MODEL_DIR", Path(__file__).resolve().parents[1] / "models")).resolve()
    backtests_dir = models_dir / "backtests"
    if not backtests_dir.exists():
        raise HTTPException(status_code=404, detail="No backtest directory present")

    if symbol:
        key = symbol.replace("/", "_")
        candidates = sorted(backtests_dir.glob(f"equity_{key}_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            candidates = sorted(backtests_dir.glob(f"equity_{key}.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return {"file": candidates[0].name}

    all_pngs = sorted(backtests_dir.glob("equity_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    if all_pngs:
        return {"file": all_pngs[0].name}

    raise HTTPException(status_code=404, detail="No backtest image found")

@router.get("/backtest/raw")
def backtest_raw(file: str = Query(...)):
    models_dir = Path(os.getenv("MODEL_DIR", Path(__file__).resolve().parents[1] / "models")).resolve()
    p = models_dir / "backtests" / file
    if not p.exists():
        raise HTTPException(status_code=404, detail="file missing")
    return FileResponse(path=str(p), media_type="image/png", filename=p.name)
