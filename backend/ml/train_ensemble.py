# predictor/backend/ml/train_ensemble.py
"""
Train ensemble stack for a symbol/timeframe predicting next return.

Usage:
    PYTHONPATH=.. python train_ensemble.py --symbol AAPL --timeframe 1d
"""

import os, json, argparse
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error
import joblib
import lightgbm as lgb
import xgboost as xgb
from feature_pipeline import prepare_feature_matrix
from model_registry import register_model

MODEL_DIR = Path(os.getenv("MODEL_DIR", "../models")).resolve()
MODEL_DIR.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------
def train_base_models(X_train, y_train, X_valid, y_valid):
    models = {}

    lgbm = lgb.LGBMRegressor(objective="regression", n_estimators=500,
                             learning_rate=0.05, random_state=42)
    try:
        lgbm.fit(X_train, y_train,
                 eval_set=[(X_valid, y_valid)],
                 early_stopping_rounds=50, verbose=False)
    except TypeError:
        lgbm.fit(X_train, y_train)
    models["lgbm"] = lgbm

    xg = xgb.XGBRegressor(n_estimators=500, learning_rate=0.05,
                          random_state=42, verbosity=0)
    try:
        xg.fit(X_train, y_train,
               eval_set=[(X_valid, y_valid)],
               early_stopping_rounds=50, verbose=False)
    except TypeError:
        xg.fit(X_train, y_train)
    models["xgb"] = xg

    rf = RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1)
    rf.fit(X_train, y_train)
    models["rf"] = rf

    return models


def oof_stacking(X, y, n_splits=5):
    """
    Produce out-of-fold predictions for stacking.
    Safe version: resets index to avoid out-of-bounds errors.
    """
    # Ensure X and y are aligned and have contiguous integer index
    X = X.reset_index(drop=True)
    y = y.reset_index(drop=True)

    n = len(X)
    if n < n_splits * 2:
        raise ValueError(f"Not enough samples ({n}) for {n_splits}-fold TimeSeriesSplit.")

    tscv = TimeSeriesSplit(n_splits=n_splits)
    base_names = ["lgbm", "xgb", "rf"]
    meta_oof = pd.DataFrame(index=range(n), columns=base_names, dtype=float)

    for fold, (train_idx, valid_idx) in enumerate(tscv.split(X), 1):
        if len(valid_idx) < 10:
            print(f"Skipping fold {fold}: too few validation samples ({len(valid_idx)})")
            continue
        X_tr, X_val = X.iloc[train_idx], X.iloc[valid_idx]
        y_tr, y_val = y.iloc[train_idx], y.iloc[valid_idx]
        models = train_base_models(X_tr, y_tr, X_val, y_val)
        for name, m in models.items():
            preds = m.predict(X_val)
            meta_oof.iloc[valid_idx, meta_oof.columns.get_loc(name)] = preds
        print(f"Fold {fold}: trained base models, filled OOF for {len(valid_idx)} rows")

    valid_mask = meta_oof.notna().all(axis=1)
    print(f"OOF produced. Valid rows: {valid_mask.sum()} / {len(meta_oof)}")
    return meta_oof.loc[valid_mask], y.loc[valid_mask]


def train_stack_and_save(symbol, timeframe, horizon=1):
    X, y, y_clf, df_full = prepare_feature_matrix(symbol=symbol, timeframe=timeframe, horizon=horizon)
    if X.empty:
        raise RuntimeError(f"No data for {symbol}/{timeframe}")

    # clean & align
    X = X.replace([np.inf, -np.inf], np.nan).dropna()
    y = y.loc[X.index].dropna()
    X, y = X.align(y, join="inner", axis=0)

    print(f"Training {symbol}/{timeframe} on {len(X)} samples")
    meta_X, meta_y = oof_stacking(X, y, n_splits=5)

    # Clean NaNs before fitting meta model
    valid_mask = meta_X.notna().all(axis=1) & meta_y.notna()
    meta_X = meta_X.loc[valid_mask]
    meta_y = meta_y.loc[valid_mask]
    print(f"Training meta-model on {len(meta_X)} rows after NaN cleanup")

    meta = Ridge(alpha=1.0)
    meta.fit(meta_X, meta_y)
    meta_preds = meta.predict(meta_X)
    meta_rmse = np.sqrt(mean_squared_error(meta_y, meta_preds))
    print("Meta RMSE (OOF):", meta_rmse)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"{symbol.replace('/','_')}_{timeframe}_{ts}"

    # Save meta
    meta_file = MODEL_DIR / f"meta_stack_{name}.joblib"
    joblib.dump({"meta": meta, "base_cols": list(meta_X.columns)}, meta_file)
    print("Saved meta stack:", meta_file)

    # Train full-data base models
    base_models = train_base_models(X, y, X, y)
    base_files = {}
    for nm, model in base_models.items():
        bf = MODEL_DIR / f"base_{name}_{nm}.joblib"
        joblib.dump(model, bf)
        base_files[nm] = bf.name
        print("Saved base model:", bf)

    metadata = {
        "symbol": symbol,
        "timeframe": timeframe,
        "horizon": horizon,
        "meta_file": meta_file.name,
        "base_files": base_files,
        "meta_rmse_oof": float(meta_rmse),
        "features": list(X.columns),
        "trained_at": ts,
    }
    meta_path = MODEL_DIR / f"metadata_ensemble_{name}.json"
    meta_path.write_text(json.dumps(metadata, indent=2))
    latest_path = MODEL_DIR / "latest_ensemble.json"
    latest_path.write_text(
        json.dumps(
            {"ensemble_meta": meta_file.name,
             "base_models": base_files,
             "features": list(X.columns)}
        )
    )

    try:
        register_model(
            name=f"ensemble_{name}",
            symbol=symbol,
            model_path=meta_file.name,
            booster_path=None,
            features=list(X.columns),
            metrics={"meta_rmse_oof": meta_rmse},
            params={"algos": list(base_files.keys())},
        )
        print("Registered ensemble model.")
    except Exception as e:
        print("Registry registration failed:", e)

    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--horizon", type=int, default=1)
    args = parser.parse_args()
    meta = train_stack_and_save(args.symbol, args.timeframe, args.horizon)
    print("✅ Done. Metadata:", meta)
