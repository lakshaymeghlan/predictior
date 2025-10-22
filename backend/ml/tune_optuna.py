# predictor/backend/ml/tune_optuna.py
"""
Tuning + walk-forward CV for LightGBM using Optuna.

This version is robust to LightGBM builds that have different train() signatures.
It tries:
 - lgb.train(..., callbacks=[lgb.early_stopping(...), lgb.log_evaluation(0)])
 - fallback to lgb.train(..., early_stopping_rounds=...)
 - fallback to lgb.train(...)

Saves:
 - native LightGBM booster: lgb_booster_<symbol>_<ts>.txt
 - picklable joblib wrapper: lgb_model_<symbol>_<ts>.joblib (if possible)
 - metadata_*.json and latest.json
 - registers the model in registry.db (sqlite) if model_registry available

Usage:
    cd predictor/backend/ml
    pip install optuna
    python tune_optuna.py --trials 6
"""

import os
import json
from pathlib import Path
import optuna
import lightgbm as lgb
import numpy as np
import joblib
from datetime import datetime, timezone
from sklearn.metrics import mean_squared_error
from dotenv import load_dotenv
from feature_pipeline import prepare_feature_matrix

# registry helper - should be in same folder as this script
try:
    from model_registry import register_model
except Exception:
    register_model = None  # optional

load_dotenv()

MODEL_DIR = Path(os.getenv("MODEL_DIR", "../models")).resolve()
MODEL_DIR.mkdir(parents=True, exist_ok=True)

SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
HORIZON = int(os.getenv("HORIZON", "1"))

# -------------------------
# Top-level wrapper class (picklable)
# -------------------------
class SimpleBoosterWrapper:
    """Top-level wrapper around lightgbm.Booster to keep joblib picklable."""
    def __init__(self, booster, features):
        self.booster = booster
        self.features = list(features)

    def predict(self, X_df, num_iteration=None):
        if hasattr(X_df, "values"):
            arr = X_df.values
        else:
            arr = X_df
        return self.booster.predict(arr)

# -------------------------
# Walk-forward splits
# -------------------------
def walk_forward_splits(n_splits=5, min_train_size=1000, test_size=1000, indices=None):
    """
    Yield rolling train/test index lists.
    """
    n = len(indices)
    start = 0
    while True:
        train_start = start
        train_end = train_start + min_train_size
        test_start = train_end
        test_end = test_start + test_size
        if test_end > n:
            break
        yield list(range(train_start, train_end)), list(range(test_start, test_end))
        start += test_size

# -------------------------
# Robust train helper
# -------------------------
def train_with_optional_earlystop(params, dtrain, dvalid=None, num_boost_round=500, early_stop_rounds=50):
    """
    Try multiple lgb.train signatures for compatibility across LightGBM builds.
    Returns a trained Booster.
    """
    # Try modern callbacks API first
    try:
        callbacks = []
        try:
            callbacks.append(lgb.early_stopping(stopping_rounds=early_stop_rounds))
            callbacks.append(lgb.log_evaluation(period=0))
        except Exception:
            # some builds may expose differently; ignore if unavailable
            pass
        if dvalid is not None:
            booster = lgb.train(
                params,
                dtrain,
                num_boost_round=num_boost_round,
                valid_sets=[dvalid],
                callbacks=callbacks
            )
        else:
            booster = lgb.train(
                params,
                dtrain,
                num_boost_round=num_boost_round,
                callbacks=callbacks
            )
        return booster
    except TypeError as e:
        # fallback to older early_stopping_rounds kwarg
        try:
            if dvalid is not None:
                booster = lgb.train(
                    params,
                    dtrain,
                    num_boost_round=num_boost_round,
                    valid_sets=[dvalid],
                    early_stopping_rounds=early_stop_rounds,
                )
            else:
                booster = lgb.train(params, dtrain, num_boost_round=num_boost_round)
            return booster
        except TypeError:
            # final fallback: plain train without early stopping
            if dvalid is not None:
                booster = lgb.train(params, dtrain, num_boost_round=num_boost_round, valid_sets=[dvalid])
            else:
                booster = lgb.train(params, dtrain, num_boost_round=num_boost_round)
            return booster
    except Exception:
        # any other exception -> final fallback
        if dvalid is not None:
            booster = lgb.train(params, dtrain, num_boost_round=num_boost_round, valid_sets=[dvalid])
        else:
            booster = lgb.train(params, dtrain, num_boost_round=num_boost_round)
        return booster

# -------------------------
# Objective for Optuna
# -------------------------
def objective(trial, X, y):
    params = {
        "objective": "regression",
        "metric": "rmse",
        "learning_rate": trial.suggest_float("learning_rate", 1e-4, 1e-1, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 16, 256),
        "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 5, 200),
        "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
        "bagging_freq": trial.suggest_int("bagging_freq", 0, 10),
        "lambda_l1": trial.suggest_float("lambda_l1", 0.0, 5.0),
        "lambda_l2": trial.suggest_float("lambda_l2", 0.0, 5.0),
        "verbose": -1,
    }

    indices = list(range(len(X)))
    splits = list(
        walk_forward_splits(
            n_splits=5,
            min_train_size=max(1000, int(len(X) * 0.2)),
            test_size=max(100, int(len(X) * 0.1)),
            indices=indices,
        )
    )

    rmses = []
    for train_idx, test_idx in splits:
        X_train = X.iloc[train_idx]
        y_train = y.iloc[train_idx]
        X_test = X.iloc[test_idx]
        y_test = y.iloc[test_idx]

        dtrain = lgb.Dataset(X_train, label=y_train)
        dvalid = lgb.Dataset(X_test, label=y_test, reference=dtrain)

        booster = train_with_optional_earlystop(params, dtrain, dvalid=dvalid, num_boost_round=500, early_stop_rounds=50)

        preds = booster.predict(X_test)
        rmse = np.sqrt(mean_squared_error(y_test, preds))
        rmses.append(rmse)

    return float(np.mean(rmses))

# -------------------------
# Runner
# -------------------------
def run_optuna_trials(n_trials=40):
    print("Loading features and target from feature_pipeline...")
    X, y, y_clf, _ = prepare_feature_matrix(symbol=SYMBOL, horizon=HORIZON)
    X = X.replace([np.inf, -np.inf], np.nan).dropna()
    y = y.loc[X.index]

    def _obj(trial):
        return objective(trial, X, y)

    study = optuna.create_study(direction="minimize", study_name=f"lgb_{SYMBOL.replace('/', '_')}")
    study.optimize(_obj, n_trials=n_trials, show_progress_bar=True)

    print("✅ Best params:", study.best_params)
    best_params = study.best_params
    best_params.update({"objective": "regression", "metric": "rmse", "verbose": -1})

    # Train final booster on full data using robust helper
    dtrain = lgb.Dataset(X, label=y)
    booster = train_with_optional_earlystop(best_params, dtrain, dvalid=None, num_boost_round=1000, early_stop_rounds=50)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    booster_file = MODEL_DIR / f"lgb_booster_{SYMBOL.replace('/', '_')}_{ts}.txt"
    booster.save_model(str(booster_file))
    print("Saved native booster ->", booster_file)

    # Create picklable wrapper and attempt to save via joblib
    wrapper = SimpleBoosterWrapper(booster, list(X.columns))
    joblib_file = MODEL_DIR / f"lgb_model_{SYMBOL.replace('/', '_')}_{ts}.joblib"

    joblib_ok = False
    try:
        joblib.dump(wrapper, joblib_file)
        joblib_ok = True
        print("Saved joblib wrapper ->", joblib_file)
    except Exception as e:
        print("Warning: joblib.dump failed for wrapper (will continue). Error:", e)
        joblib_ok = False

    # Save metadata & latest pointer
    metadata = {
        "symbol": SYMBOL,
        "features": list(X.columns),
        "params": best_params,
        "ts": ts,
        "booster_file": booster_file.name,
        "joblib_file": joblib_file.name if joblib_ok else None,
        "best_cv_rmse": float(study.best_value) if hasattr(study, "best_value") else None,
    }
    meta_file = MODEL_DIR / f"metadata_{SYMBOL.replace('/', '_')}_{ts}.json"
    meta_file.write_text(json.dumps(metadata, indent=2))

    latest_path = MODEL_DIR / "latest.json"
    latest_content = {"booster_file": booster_file.name, "features": list(X.columns)}
    if joblib_ok:
        latest_content["model_file"] = joblib_file.name
    latest_path.write_text(json.dumps(latest_content))

    # Register model if registry present
    if register_model is not None:
        try:
            register_model(
                name=f"lgb_{SYMBOL.replace('/', '_')}_{ts}",
                symbol=SYMBOL,
                model_path=joblib_file.name if joblib_ok else booster_file.name,
                booster_path=booster_file.name,
                features=list(X.columns),
                metrics={"best_cv_rmse": metadata["best_cv_rmse"]},
                params=best_params,
            )
            print("Registered model in registry.db")
        except Exception as e:
            print("Warning: model registry registration failed:", e)

    print("💾 Saved metadata:", meta_file)
    return study, metadata

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=40)
    args = parser.parse_args()
    study, meta = run_optuna_trials(n_trials=args.trials)
    print("✅ Done.")
