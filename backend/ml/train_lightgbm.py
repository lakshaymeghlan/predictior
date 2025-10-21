# train_lightgbm.py (robust, saves native LightGBM booster + joblib)
import os
import json
from datetime import datetime, timezone
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score, accuracy_score, f1_score
from lightgbm import LGBMRegressor
import lightgbm as lgb
import joblib
import numpy as np
from dotenv import load_dotenv
from feature_pipeline import prepare_feature_matrix
from pathlib import Path

load_dotenv()

MODEL_DIR = os.getenv("MODEL_DIR", "../models")
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
TEST_SIZE_PCT = float(os.getenv("TEST_SIZE_PCT", "0.2"))
HORIZON = 1
EARLY_STOPPING_ROUNDS = 50
NUM_BOOST_ROUND = 1000

Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)


class BoosterWrapper:
    """
    Module-level wrapper for a lightgbm.Booster so joblib can pickle it.
    Exposes .predict(X, num_iteration=None) and .best_iteration_ for compatibility.
    """
    def __init__(self, booster: lgb.Booster):
        self.booster = booster
        bi = getattr(booster, "best_iteration", None)
        self.best_iteration_ = bi if (bi is not None and bi > 0) else None

    def predict(self, X, num_iteration=None):
        if num_iteration is None:
            return self.booster.predict(X)
        return self.booster.predict(X, num_iteration=num_iteration)

    def save_model(self, path):
        return self.booster.save_model(str(path))

    @classmethod
    def load_model(cls, path):
        b = lgb.Booster(model_file=str(path))
        return cls(b)


def time_train_test_split(X, y, test_pct=0.2):
    n = len(X)
    split_idx = int(n * (1 - test_pct))
    X_train = X.iloc[:split_idx]
    X_test = X.iloc[split_idx:]
    y_train = y.iloc[:split_idx]
    y_test = y.iloc[split_idx:]
    return X_train, X_test, y_train, y_test


def train_and_save():
    X, y, y_clf, df_full = prepare_feature_matrix(horizon=HORIZON)

    if len(X) < 200:
        raise RuntimeError(f"Not enough rows to train (need >=200, got {len(X)}).")

    X = X.replace([np.inf, -np.inf], np.nan).dropna()
    y = y.loc[X.index]
    y_clf = y_clf.loc[X.index]

    X_train, X_test, y_train, y_test = time_train_test_split(X, y, test_pct=TEST_SIZE_PCT)
    print(f"Train shape: {X_train.shape}, Test shape: {X_test.shape}")

    sklearn_model = LGBMRegressor(
        objective="regression",
        learning_rate=0.05,
        num_leaves=31,
        n_estimators=NUM_BOOST_ROUND,
        min_child_samples=20,
        verbosity=-1,
        random_state=42,
    )

    best_iter = None
    used_api = None
    model = None
    native_booster = None

    # Try sklearn API
    try:
        sklearn_model.fit(
            X_train,
            y_train,
            eval_set=[(X_train, y_train), (X_test, y_test)],
            eval_metric="rmse",
            early_stopping_rounds=EARLY_STOPPING_ROUNDS,
            verbose=50,
        )
        best_iter = getattr(sklearn_model, "best_iteration_", None)
        model = sklearn_model
        used_api = "sklearn_lgbm"
        print("Trained with sklearn LGBMRegressor.")
        # attempt to extract native booster if available (sklearn wrapper exposes booster_)
        try:
            native_booster = sklearn_model.booster_
        except Exception:
            native_booster = None
    except TypeError as e:
        print("sklearn LGBMRegressor.fit() unsupported args — falling back to lgb.train().")
        print("TypeError:", e)
        # fallback to classic API
        dtrain = lgb.Dataset(X_train, label=y_train)
        dvalid = lgb.Dataset(X_test, label=y_test, reference=dtrain)
        params = {
            "objective": "regression",
            "metric": "rmse",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "min_data_in_leaf": 20,
            "verbose": -1
        }
        try:
            booster = lgb.train(
                params,
                dtrain,
                num_boost_round=NUM_BOOST_ROUND,
                valid_sets=[dtrain, dvalid],
                early_stopping_rounds=EARLY_STOPPING_ROUNDS,
                verbose_eval=50,
            )
            best_iter = getattr(booster, "best_iteration", None) or getattr(booster, "current_iteration", None)
            print("Trained with lightgbm.train() using early stopping.")
        except TypeError as e2:
            print("lgb.train() does not support early_stopping_rounds on this build — training without early stopping.")
            print("TypeError:", e2)
            booster = lgb.train(
                params,
                dtrain,
                num_boost_round=NUM_BOOST_ROUND,
                valid_sets=[dtrain, dvalid],
            )
            best_iter = getattr(booster, "best_iteration", None)
            print("Trained with lightgbm.train() without early stopping.")

        native_booster = booster
        model = BoosterWrapper(booster)
        used_api = "lgb_train"

    # Predictions for metrics
    num_iter = best_iter if (best_iter is not None and best_iter > 0) else None
    try:
        preds_test = model.predict(X_test, num_iteration=num_iter)
        preds_train = model.predict(X_train, num_iteration=num_iter)
    except TypeError:
        preds_test = model.predict(X_test)
        preds_train = model.predict(X_train)

    mse = mean_squared_error(y_test, preds_test)
    mae = mean_absolute_error(y_test, preds_test)
    r2 = r2_score(y_test, preds_test)

    preds_test_bin = (preds_test > 0).astype(int)
    acc = accuracy_score(y_clf.loc[X_test.index], preds_test_bin)
    f1 = f1_score(y_clf.loc[X_test.index], preds_test_bin)

    print("Test MSE:", mse)
    print("Test MAE:", mae)
    print("Test R2:", r2)
    print("Test Accuracy (up/down):", acc, "F1:", f1)

    # Save artifacts:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    model_joblib_path = Path(MODEL_DIR) / f"lgb_model_{SYMBOL.replace('/','_')}_{ts}.joblib"
    joblib.dump(model, model_joblib_path)
    print("Saved joblib model to:", model_joblib_path)

    booster_path = None
    if native_booster is not None:
        booster_path = Path(MODEL_DIR) / f"lgb_booster_{SYMBOL.replace('/','_')}_{ts}.txt"
        native_booster.save_model(str(booster_path))
        print("Saved native LightGBM booster to:", booster_path)

    metadata = {
        "symbol": SYMBOL,
        "timeframe": "1h",
        "horizon_hours": HORIZON,
        "train_rows": len(X_train),
        "test_rows": len(X_test),
        "mse": float(mse),
        "mae": float(mae),
        "r2": float(r2),
        "accuracy_updown": float(acc),
        "f1_updown": float(f1),
        "joblib_model": str(model_joblib_path),
        "booster_model": str(booster_path) if booster_path is not None else None,
        "features": X.columns.tolist(),
        "trained_at_utc": ts,
        "used_api": used_api
    }
    meta_path = Path(MODEL_DIR) / f"metadata_{SYMBOL.replace('/','_')}_{ts}.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print("Saved metadata to:", meta_path)

    # latest.json (loader uses this)
    latest = {
        "joblib_model": str(model_joblib_path),
        "booster_model": str(booster_path) if booster_path is not None else None,
        "features": X.columns.tolist()
    }
    with open(Path(MODEL_DIR) / "latest.json", "w") as f:
        json.dump(latest, f)

    return model, metadata


if __name__ == "__main__":
    train_and_save()
