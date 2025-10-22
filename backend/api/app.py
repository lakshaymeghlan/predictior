# predictor/backend/api/app.py
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import sys, os, json, joblib, math
import lightgbm as lgb
import numpy as np
import pandas as pd
from dotenv import load_dotenv

# Import routers (package-relative)
from .auth import router as auth_router, get_current_user
from .billing import router as billing_router
from .quota import consume_quota
from .alerts import router as alerts_router
from .dashboard import router as dashboard_router
from .db import init_db

# ensemble predictor (ml folder must be in sys.path at runtime)
# we will import lazily inside route; not at module import time to avoid import cycles

# initialize DB
init_db()

# create FastAPI app
app = FastAPI(title="Predictor API", version="0.1")

# include routers
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(alerts_router)
app.include_router(dashboard_router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# load ML env (optional)
repo_root = Path(__file__).resolve().parents[2]
ml_env = repo_root / "backend" / "ml" / ".env"
if ml_env.exists():
    load_dotenv(dotenv_path=str(ml_env))
else:
    load_dotenv()

MODEL_DIR = Path(os.getenv("MODEL_DIR", "../models")).resolve()
LATEST_JSON = MODEL_DIR / "latest.json"

class PredictResponse(BaseModel):
    symbol: str
    period: str
    ts: str
    model_version: str
    pred_next_1h_return: float
    pred_prob_up: float | None = None
    note: str | None = None

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
        if p.suffix == ".txt" or p.suffix == ".model":
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

    if model_file is not None:
        try:
            return _load_by_path(model_file, features)
        except Exception as e:
            print("Warning: failed loading model_file from latest.json:", e)

    boosters = sorted(MODEL_DIR.glob("lgb_booster_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if boosters:
        try:
            return _load_by_path(boosters[0], features)
        except Exception as e:
            print("Warning: failed loading newest booster file:", e)

    joblibs = sorted(MODEL_DIR.glob("lgb_model_*.joblib"), key=lambda p: p.stat().st_mtime, reverse=True)
    if joblibs:
        try:
            return _load_by_path(joblibs[0], features)
        except Exception as e:
            print("Warning: failed loading newest joblib file:", e)

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

    raise RuntimeError("No valid model artifact found in MODEL_DIR and latest.json. Please run training to produce a model.")

@app.get("/predict", response_model=PredictResponse)
def predict(
    symbol: str = Query("BTC/USDT"),
    period: str = Query("1h"),
    timeframe: str = Query("1h"),
    use_ensemble: bool = Query(False),
    user = Depends(consume_quota(required=1))
):
    import math
    # lazy add ml path to sys.path
    repo_root = Path(__file__).resolve().parents[2]
    ml_path = repo_root / "backend" / "ml"
    if str(ml_path) not in sys.path:
        sys.path.insert(0, str(ml_path))

    try:
        from feature_pipeline import prepare_feature_matrix
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Feature pipeline import failed: {e}"})

    try:
        X, y, y_clf, df_full = prepare_feature_matrix(symbol, timeframe, horizon=1)
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Feature preparation failed: {e}"})

    if X.empty:
        return JSONResponse(status_code=500, content={"detail": "No features available for symbol/timeframe."})

    last_index = X.index[-1]
    last_row = X.iloc[-1].to_dict()

    if use_ensemble:
        try:
            from ensemble_predictor import predict_ensemble_row
            pred = predict_ensemble_row(last_row)
            prob_up = 1.0 / (1.0 + math.exp(-pred * 100))
            return PredictResponse(
                symbol=symbol,
                period=period,
                ts=str(last_index),
                model_version="ensemble_latest",
                pred_next_1h_return=float(pred),
                pred_prob_up=float(prob_up),
                note="ensemble"
            )
        except Exception as e:
            print(f"[WARN] Ensemble predict failed, falling back: {e}")

    try:
        info = load_model_info()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Model load failed: {e}"})

    model_features = info["features"]
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

@app.get("/backtest/latest")
def backtest_latest():
    backtest_pngs = sorted(MODEL_DIR.glob("backtests/equity_*.png"), reverse=True)
    if backtest_pngs:
        latest_png = backtest_pngs[0]
        return FileResponse(path=str(latest_png), media_type="image/png", filename=latest_png.name)

    backtests = sorted(MODEL_DIR.glob("backtests/equity_*.csv"), reverse=True)
    if backtests:
        latest = backtests[0]
        return FileResponse(path=str(latest), media_type="text/csv", filename=latest.name)

    raise HTTPException(status_code=404, detail="No backtest results found.")
