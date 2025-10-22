# predictor/backend/ml/ensemble_predictor.py
import joblib
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
import os, json

load_dotenv()
MODEL_DIR = Path(os.getenv("MODEL_DIR","../models")).resolve()

def load_ensemble_for_latest():
    latest = MODEL_DIR / "latest_ensemble.json"
    if not latest.exists():
        raise FileNotFoundError("latest_ensemble.json not found")
    info = json.loads(latest.read_text())
    meta_file = MODEL_DIR / info["ensemble_meta"]
    meta = joblib.load(meta_file)
    base_models = {}
    for name, fname in info["base_models"].items():
        base_models[name] = joblib.load(MODEL_DIR / fname)
    return meta, base_models

def predict_ensemble_row(row):
    """
    row: dict or 1-row DataFrame with same features used during training
    returns: numeric blended prediction
    """
    meta, base_models = load_ensemble_for_latest()
    # make DataFrame
    df = pd.DataFrame([row], columns=meta["base_cols"] if isinstance(meta, dict) and "base_cols" in meta else row.keys())
    # get base preds
    base_preds = {}
    for name, m in base_models.items():
        base_preds[name] = m.predict(df)
    # build meta row
    meta_row = pd.DataFrame({k: v[0] for k, v in base_preds.items()}, index=[0])
    blended = meta["meta"].predict(meta_row) if isinstance(meta, dict) else meta.predict(meta_row)
    return float(blended[0])
