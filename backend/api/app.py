# backend/api/app.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import sys, os, json, joblib, math, traceback
import lightgbm as lgb
from dotenv import load_dotenv
from typing import Tuple

# --- helper to import routers safely ---
# replace existing import_router with this improved, verbose version
def import_router(path: str, name: str):
    try:
        module = __import__(path, fromlist=[name])
        router = getattr(module, name)
        print(f"[OK] imported {path}.{name}")
        return router
    except Exception as e:
        # print a clear warning and the full traceback so we can see why imports fail
        import traceback
        print(f"[WARN] Failed to import {path}.{name}: {e}")
        traceback.print_exc()
        return None


# load ML env if present
# load ML env if present
repo_root = Path(__file__).resolve().parents[2]
ml_env = repo_root / "backend" / "ml" / ".env"
if ml_env.exists():
    load_dotenv(dotenv_path=str(ml_env))
else:
    # also attempt to load backend/api/.env (your per-backend overrides)
    api_env = repo_root / "backend" / "api" / ".env"
    if api_env.exists():
        load_dotenv(dotenv_path=str(api_env))
    else:
        load_dotenv()

# Prefer explicit MODEL_DIR env var, otherwise default to repo_root/backend/models
MODEL_DIR = Path(os.getenv("MODEL_DIR", str(repo_root / "backend" / "models"))).resolve()
LATEST_JSON = MODEL_DIR / "latest.json"

print("DEBUG: app.py MODEL_DIR resolved to:", MODEL_DIR)

# create app
app = FastAPI(title="Predictor API", version="0.1")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Import optional routers by module path (they should expose `router`)
auth_router = import_router("backend.api.auth", "router")
dashboard_router = import_router("backend.api.dashboard", "router")
billing_router = import_router("backend.api.billing", "router")
quota_router = import_router("backend.api.quota", "router")
alerts_router = import_router("backend.api.alerts", "router")
market_router = import_router("backend.api.market", "router")

# include routers if available
if auth_router is not None:
    app.include_router(auth_router)
if dashboard_router is not None:
    app.include_router(dashboard_router)
if billing_router is not None:
    app.include_router(billing_router)
if quota_router is not None:
    app.include_router(quota_router)
if alerts_router is not None:
    app.include_router(alerts_router)
if market_router is not None:
    app.include_router(market_router)

# --- small helper to list routes at startup ---
@app.on_event("startup")
def log_routes_on_startup():
    print("=== Registered routes ===")
    for r in sorted(app.routes, key=lambda x: getattr(x, "path", "")):
        try:
            methods = ",".join(sorted(getattr(r, "methods", []) or []))
            path = getattr(r, "path", str(r))
            name = getattr(r, "name", "")
            print(f"{path:40s}  {methods:15s}  {name}")
        except Exception:
            pass
    print("=========================")

# --- input normalization helper ---
def normalize_symbol_and_timeframe(symbol: str, timeframe: str) -> Tuple[str, str]:
    """
    Accept common user mistakes:
      - symbol passed as "GLD/1h" (combined symbol+tf)
      - symbol passed as "GLD_1h" (underscore)
    Always return (symbol, timeframe) where symbol is e.g. "GLD" or "BTC/USDT"
    and timeframe is e.g. "1h".
    """
    symbol = (symbol or "").strip()
    timeframe = (timeframe or "").strip()
    # if symbol contains trailing timeframe token like "1h" treat accordingly
    if not timeframe and ("/" in symbol or "_" in symbol):
        # try slash/underscore split
        parts = symbol.replace("_", "/").split("/")
        if parts and parts[-1] in ("1h", "4h", "1d", "1m", "5m", "15m"):
            timeframe = parts[-1]
            symbol = "/".join(parts[:-1]) or symbol
    # if symbol looks like pair with underscore file format, keep it as slash for API
    symbol = symbol.strip()
    if "_" in symbol and "/" not in symbol and len(symbol.split("_")) in (2, 3):
        symbol = symbol.replace("_", "/")
    return symbol, (timeframe or "1h")

# === model loader (robust) ===

def load_model_info(symbol: str | None = None):
    """
    Load model info. If `symbol` is provided, prefer symbol-specific artifacts:
    - lgb_booster_{SYMBOL}_*.txt
    - lgb_model_{SYMBOL}_*.joblib
    - metadata_{SYMBOL}.json
    If none found, fall back to previous generic scanning behavior.
    """
    info_path = LATEST_JSON
    info = {}
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text())
        except Exception:
            info = {}

    features = info.get("features") or info.get("feature_list") or None

    def _load_by_path(p: Path, features_list):
        p = p.resolve()
        if not p.exists():
            raise FileNotFoundError(f"Model file not found: {p}")
        if p.suffix in (".txt", ".model"):
            booster = lgb.Booster(model_file=str(p))
            return {"type": "booster", "model": booster, "features": features_list or [], "version": p.name}
        if p.suffix in (".joblib", ".pkl"):
            mdl = joblib.load(str(p))
            return {"type": "joblib", "model": mdl, "features": features_list or [], "version": p.name}
        try:
            booster = lgb.Booster(model_file=str(p))
            return {"type": "booster", "model": booster, "features": features_list or [], "version": p.name}
        except Exception:
            mdl = joblib.load(str(p))
            return {"type": "joblib", "model": mdl, "features": features_list or [], "version": p.name}

    # 1) If LATEST_JSON explicitly points to a model file and it exists, use it (same as before)
    model_file = None
    if "model_file" in info:
        model_file = MODEL_DIR / info["model_file"] if not Path(info["model_file"]).is_absolute() else Path(info["model_file"])
    elif "booster_file" in info:
        model_file = MODEL_DIR / info["booster_file"] if not Path(info["booster_file"]).is_absolute() else Path(info["booster_file"])
    elif "model_path" in info:
        model_file = MODEL_DIR / info["model_path"] if not Path(info["model_path"]).is_absolute() else Path(info["model_path"])

    if model_file is not None:
        try:
            return _load_by_path(model_file, features)
        except Exception:
            pass

    # 2) Try symbol-specific artifacts (if symbol provided)
    if symbol:
        s_key = symbol.replace("/", "_")
        # check metadata_{symbol}.json first
        try:
            meta_file = MODEL_DIR / f"metadata_{s_key}.json"
            if meta_file.exists():
                mj = json.loads(meta_file.read_text())
                possible = mj.get("model_path") or mj.get("model_file") or mj.get("model")
                if possible:
                    p = Path(possible)
                    if not p.is_absolute():
                        p = MODEL_DIR / p
                    return _load_by_path(p, mj.get("features") or features)
        except Exception:
            pass

        # check booster / joblib with symbol in name
        try:
            boosters_sym = sorted(MODEL_DIR.glob(f"lgb_booster_{s_key}_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
            if boosters_sym:
                return _load_by_path(boosters_sym[0], features)
        except Exception:
            pass

        try:
            joblibs_sym = sorted(MODEL_DIR.glob(f"lgb_model_{s_key}_*.joblib"), key=lambda p: p.stat().st_mtime, reverse=True)
            if joblibs_sym:
                return _load_by_path(joblibs_sym[0], features)
        except Exception:
            pass

    # 3) Fallback to global scanning behavior (existing logic)
    boosters = sorted(MODEL_DIR.glob("lgb_booster_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if boosters:
        try:
            return _load_by_path(boosters[0], features)
        except Exception:
            pass

    joblibs = sorted(MODEL_DIR.glob("lgb_model_*.joblib"), key=lambda p: p.stat().st_mtime, reverse=True)
    if joblibs:
        try:
            return _load_by_path(joblibs[0], features)
        except Exception:
            pass

    metas = sorted(MODEL_DIR.glob("metadata_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for m in metas:
        try:
            mj = json.loads(m.read_text())
            possible = mj.get("model_path") or mj.get("model_file") or mj.get("model") or None
            if possible:
                p = Path(possible)
                if not p.is_absolute():
                    p = MODEL_DIR / p
                return _load_by_path(p, mj.get("features"))
        except Exception:
            continue

    raise RuntimeError("No valid model artifact found in MODEL_DIR / latest.json. Run training to create model artifacts.")

# simple predict endpoint
class PredictResponse(BaseModel):
    symbol: str
    period: str
    ts: str
    model_version: str
    pred_next_1h_return: float
    pred_prob_up: float | None = None
    note: str | None = None

@app.get("/predict", response_model=PredictResponse)
def predict(symbol: str = "BTC/USDT", period: str = "1h", timeframe: str = "1h"):
    import math
    # lazy import feature pipeline
    repo_root = Path(__file__).resolve().parents[2]
    ml_path = repo_root / "backend" / "ml"
    if str(ml_path) not in sys.path:
        sys.path.insert(0, str(ml_path))

    # Normalize sloppy inputs (e.g. symbol="GLD_1h" or "BTC/USDT/1h")
    symbol, timeframe = normalize_symbol_and_timeframe(symbol, timeframe)

    try:
        from feature_pipeline import prepare_feature_matrix
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Feature pipeline import failed: {e}"})
    try:
        X, y, y_clf, df_full = prepare_feature_matrix(symbol=symbol, timeframe=timeframe, horizon=1)
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Feature preparation failed: {e}"})

    if X.empty:
        # helpful hint so frontend user sees what to fix
        file_hint = f"{symbol.replace('/','_')}_{timeframe}.csv"
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"No features available for {symbol} / {timeframe}. "
                          f"Ensure data file {file_hint} exists in the data directory and that the CSV has columns: timestamp,open,high,low,close,volume."
            }
        )

    last_index = X.index[-1]
    last_row = X.iloc[-1].to_dict()
    try:
        info = load_model_info(symbol)
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Model load failed: {e}"})
    model_features = info["features"]
    import pandas as pd
    row_df = pd.DataFrame([last_row], columns=model_features).fillna(0.0)
    model = info["model"]
    try:
        if info["type"] == "booster":
            pred = model.predict(row_df.values)[0]
        else:
            try:
                pred = model.predict(row_df)[0]
            except TypeError:
                pred = model.predict(row_df, num_iteration=None)[0]
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Model predict error: {e}"})
    prob_up = 1.0 / (1.0 + math.exp(-pred * 100))
    return PredictResponse(
        symbol=symbol,
        period=period,
        ts=str(last_index),
        model_version=info["version"],
        pred_next_1h_return=float(pred),
        pred_prob_up=float(prob_up),
        note="single-model"
    )

# backtest latest: serve png then csv
@app.get("backtest/latest")
def backtest_latest():
    backtests_dir = MODEL_DIR / "backtests"
    backtests_dir.mkdir(parents=True, exist_ok=True)
    pngs = sorted(backtests_dir.glob("equity_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    print("DEBUG: backtests_dir:", backtests_dir)
    print("DEBUG: found pngs:", pngs)
    if pngs:
        print("DEBUG: returning:", pngs[0])
        return FileResponse(path=str(pngs[0]), media_type="image/png", filename=pngs[0].name)
    csvs = sorted(backtests_dir.glob("equity_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    print("DEBUG: found csvs:", csvs)
    if csvs:
        print("DEBUG: returning csv:", csvs[0])
        return FileResponse(path=str(csvs[0]), media_type="text/csv", filename=csvs[0].name)
    print("DEBUG: no backtest results in", backtests_dir)
    raise HTTPException(status_code=404, detail="No backtest results found.")
