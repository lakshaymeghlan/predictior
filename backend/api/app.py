# backend/api/app.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import sys, os, json, joblib, math, traceback
import lightgbm as lgb
from dotenv import load_dotenv

# --- helper to import routers safely ---
def import_router(path: str, name: str):
    try:
        module = __import__(path, fromlist=[name])
        return getattr(module, name)
    except Exception as e:
        print(f"[WARN] Failed to import {path}.{name}: {e}")
        traceback.print_exc()
        return None

# load ML env if present
repo_root = Path(__file__).resolve().parents[2]
ml_env = repo_root / "backend" / "ml" / ".env"
if ml_env.exists():
    load_dotenv(dotenv_path=str(ml_env))
else:
    load_dotenv()

MODEL_DIR = Path(os.getenv("MODEL_DIR", "../models")).resolve()
LATEST_JSON = MODEL_DIR / "latest.json"

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

# === model loader (robust) ===
def load_model_info():
    info_path = LATEST_JSON
    info = {}
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text())
        except Exception:
            info = {}

    model_file = None
    features = info.get("features") or info.get("feature_list") or None

    if "model_file" in info:
        model_file = MODEL_DIR / info["model_file"] if not Path(info["model_file"]).is_absolute() else Path(info["model_file"])
    elif "booster_file" in info:
        model_file = MODEL_DIR / info["booster_file"] if not Path(info["booster_file"]).is_absolute() else Path(info["booster_file"])
    elif "model_path" in info:
        model_file = MODEL_DIR / info["model_path"] if not Path(info["model_path"]).is_absolute() else Path(info["model_path"])

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

    # try direct pointer
    if model_file is not None:
        try:
            return _load_by_path(model_file, features)
        except Exception:
            pass

    # fallback to scanning
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
    try:
        from feature_pipeline import prepare_feature_matrix
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Feature pipeline import failed: {e}"})
    try:
        X, y, y_clf, df_full = prepare_feature_matrix(symbol=symbol, timeframe=timeframe, horizon=1)
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Feature preparation failed: {e}"})
    if X.empty:
        return JSONResponse(status_code=500, content={"detail": "No features available for symbol/timeframe."})
    last_index = X.index[-1]
    last_row = X.iloc[-1].to_dict()
    try:
        info = load_model_info()
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
@app.get("/backtest/latest")
def backtest_latest():
    backtests_dir = MODEL_DIR / "backtests"
    backtests_dir.mkdir(parents=True, exist_ok=True)
    pngs = sorted(backtests_dir.glob("equity_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    if pngs:
        return FileResponse(path=str(pngs[0]), media_type="image/png", filename=pngs[0].name)
    csvs = sorted(backtests_dir.glob("equity_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if csvs:
        return FileResponse(path=str(csvs[0]), media_type="text/csv", filename=csvs[0].name)
    raise HTTPException(status_code=404, detail="No backtest results found.")
