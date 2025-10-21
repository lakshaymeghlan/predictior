from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import json, joblib, os
import lightgbm as lgb
import numpy as np
import pandas as pd
from dotenv import load_dotenv

# at top of app.py (after other imports)
from dotenv import load_dotenv
from pathlib import Path
import sys, os

# locate repo root and ml .env
repo_root = Path(__file__).resolve().parents[2]   # predictor/backend/api -> up 2 -> predictor/
ml_env = repo_root / "backend" / "ml" / ".env"

# load ml env first so PG_URI is set for feature pipeline
if ml_env.exists():
    load_dotenv(dotenv_path=str(ml_env))
else:
    # fallback: load default .env in api folder (if present)
    load_dotenv()


MODEL_DIR = Path(os.getenv("MODEL_DIR", "../models")).resolve()
LATEST_JSON = MODEL_DIR / "latest.json"

app = FastAPI(title="Predictor API", version="0.1")

# Allow local dev frontends to call API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for production restrict origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

class PredictResponse(BaseModel):
    symbol: str
    period: str
    ts: str
    model_version: str
    pred_next_1h_return: float
    pred_prob_up: float | None = None
    note: str | None = None

# Utility: load model robustly (native booster preferred)
def load_model_info():
    """
    Robust loader for model artifacts.
    Tries (in order):
      1) load MODEL_DIR/latest.json and accept keys: model_file or booster_file
      2) fallback: find newest lgb_booster_*.txt
      3) fallback: find newest lgb_model_*.joblib
    Returns: {"type": "booster"|"joblib", "model": <loaded object>, "features": <list>, "version": <str>}
    Raises RuntimeError on total failure.
    """
    # helper to try load json file
    info_path = LATEST_JSON
    info = {}
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text())
        except Exception:
            info = {}

    # Case A: latest.json contains explicit model_file or booster_file
    model_file = None
    features = info.get("features") or info.get("feature_list") or None

    if "model_file" in info:
        model_file = MODEL_DIR / info["model_file"] if not Path(info["model_file"]).is_absolute() else Path(info["model_file"])
    elif "booster_file" in info:
        model_file = MODEL_DIR / info["booster_file"] if not Path(info["booster_file"]).is_absolute() else Path(info["booster_file"])
    elif "model_path" in info:
        model_file = MODEL_DIR / info["model_path"] if not Path(info["model_path"]).is_absolute() else Path(info["model_path"])

    # Helper: load booster or joblib
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
        # unknown format: try LightGBM loader then joblib
        try:
            booster = lgb.Booster(model_file=str(p))
            return {"type": "booster", "model": booster, "features": features_list or [], "version": p.name}
        except Exception:
            mdl = joblib.load(str(p))
            return {"type": "joblib", "model": mdl, "features": features_list or [], "version": p.name}

    # If model_file resolved from JSON, try to load it
    if model_file is not None:
        try:
            return _load_by_path(model_file, features)
        except Exception as e:
            # continue to fallback scanning
            print("Warning: failed loading model_file from latest.json:", e)

    # Fallback 1: find newest lgb_booster_*.txt in MODEL_DIR
    boosters = sorted(MODEL_DIR.glob("lgb_booster_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if boosters:
        try:
            return _load_by_path(boosters[0], features)
        except Exception as e:
            print("Warning: failed loading newest booster file:", e)

    # Fallback 2: find newest lgb_model_*.joblib
    joblibs = sorted(MODEL_DIR.glob("lgb_model_*.joblib"), key=lambda p: p.stat().st_mtime, reverse=True)
    if joblibs:
        try:
            # joblib may reference custom classes; ensure train module import path is available if needed
            return _load_by_path(joblibs[0], features)
        except Exception as e:
            print("Warning: failed loading newest joblib file:", e)

    # Fallback 3: try metadata json files to infer model path
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


# Simple predict-from-row helper: accepts a 1-row dict of features
def predict_from_row(row: dict):
    info = load_model_info()
    features = info["features"]
    # convert to DataFrame single-row
    X = pd.DataFrame([row], columns=features)
    model = info["model"]
    try:
        # Booster.predict expects numpy array
        if info["type"] == "booster":
            preds = model.predict(X.values)
        else:
            try:
                preds = model.predict(X)
            except TypeError:
                preds = model.predict(X, num_iteration=None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model prediction failed: {e}")
    # output single value
    return float(preds[0]), info["version"]

@app.get("/predict", response_model=PredictResponse)
def predict(symbol: str = Query("BTC/USDT"), period: str = Query("1h")):
    """
    Compute features on-the-fly from DB and return latest model prediction.
    This requires backend/ml/feature_pipeline.py to be present and PG_URI configured in that module via .env.
    """
    # ensure ml folder is importable (adjust path if your layout differs)
    repo_root = Path(__file__).resolve().parents[2]  # predictor/backend/api -> up 2 -> predictor/
    ml_path = repo_root / "backend" / "ml"
    if str(ml_path) not in sys.path:
        sys.path.insert(0, str(ml_path))

    try:
        # import the feature pipeline you already use for training
        from feature_pipeline import prepare_feature_matrix
    except Exception as e:
        # cannot import feature pipeline — fallback to cached or dummy
        return JSONResponse(status_code=500, content={
            "detail": f"Feature pipeline import failed: {e}. Ensure backend/ml is present and PG_URI set."
        })

    # prepare features for this symbol/horizon: prepare_feature_matrix returns (X, y, y_clf, df_target)
    try:
        X, y, y_clf, df_full = prepare_feature_matrix(symbol, horizon=1)
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Feature preparation failed: {e}"})

    if X.empty:
        return JSONResponse(status_code=500, content={"detail": "No features available for symbol."})

    # take the latest feature row
    last_index = X.index[-1]
    last_row = X.iloc[-1].to_dict()

    # load model and predict
    try:
        info = load_model_info()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Model load failed: {e}"})

    # prepare DataFrame aligned to model features
    # create pandas row with feature order
    import pandas as pd
    model_features = info["features"]
    # fill missing features with NaN (predict call may fail if missing)
    row_df = pd.DataFrame([last_row], columns=model_features).fillna(0.0)

    # compute prediction
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

    # simple probability mapping: map tiny returns to a bullish probability via sigmoid scaling
    import math
    prob_up = 1.0 / (1.0 + math.exp(-pred * 100))  # scale factor 100 maps small returns to nicer range

    return PredictResponse(
        symbol=symbol,
        period=period,
        ts=str(last_index),
        model_version=info["version"],
        pred_next_1h_return=float(pred),
        pred_prob_up=float(prob_up),
        note="prediction computed from latest features"
    )

@app.get("/backtest/latest")
def backtest_latest():
    # find PNG first (plot), then CSV
    backtest_pngs = sorted(MODEL_DIR.glob("backtests/equity_*.png"), reverse=True)
    if backtest_pngs:
        latest_png = backtest_pngs[0]
        return FileResponse(path=str(latest_png), media_type="image/png", filename=latest_png.name)

    backtests = sorted(MODEL_DIR.glob("backtests/equity_*.csv"), reverse=True)
    if backtests:
        latest = backtests[0]
        return FileResponse(path=str(latest), media_type="text/csv", filename=latest.name)

    raise HTTPException(status_code=404, detail="No backtest results found.")

