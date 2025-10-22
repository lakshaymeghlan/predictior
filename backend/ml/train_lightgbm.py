# backend/ml/train_lightgbm.py
import os
import json
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
import numpy as np
import pandas as pd
import joblib
import lightgbm as lgb

from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score, accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from lightgbm import LGBMRegressor

# Top-level wrapper so joblib can pickle/unpickle it across processes
class BoosterWrapperTopLevel:
    """
    Thin top-level wrapper to hold a native LightGBM Booster and expose predict(X[, num_iteration])
    This is defined at module level so joblib/pickle can find it.
    """
    def __init__(self, booster: lgb.Booster, features=None):
        self.booster = booster
        self.features = list(features) if features is not None else []

    def predict(self, X, num_iteration=None):
        # accept DataFrame or numpy array
        if hasattr(X, "values"):
            arr = X.values
        else:
            arr = X
        if num_iteration is None:
            return self.booster.predict(arr)
        return self.booster.predict(arr, num_iteration=num_iteration)


load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / "ml" / ".env", verbose=False)

MODEL_DIR = Path(os.getenv("MODEL_DIR", "../models")).resolve()
MODEL_DIR.mkdir(parents=True, exist_ok=True)

SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
TEST_SIZE_PCT = float(os.getenv("TEST_SIZE_PCT", "0.2"))
HORIZON = int(os.getenv("HORIZON", "1"))
NUM_BOOST_ROUND = int(os.getenv("NUM_BOOST_ROUND", "1000"))
EARLY_STOPPING_ROUNDS = int(os.getenv("EARLY_STOPPING_ROUNDS", "50"))

# import local feature pipeline (must be in backend/ml/)
try:
    # if running from repo root, ensure ml path is available
    ml_folder = Path(__file__).resolve().parents[1]  # backend/ml
    if str(ml_folder) not in os.sys.path:
        os.sys.path.insert(0, str(ml_folder))
    from feature_pipeline import prepare_feature_matrix
except Exception as e:
    raise RuntimeError(f"Failed to import feature_pipeline: {e}")


def clean_xy(X: pd.DataFrame, y: pd.Series):
    """
    Defensive cleaning:
      - Replace inf with NaN
      - Drop rows where any feature is NaN
      - Align y to X index
      - Ensure numeric dtypes
    """
    X = X.copy()
    X = X.replace([np.inf, -np.inf], np.nan)
    X = X.astype(float, errors="ignore")
    # drop columns that are all NaN
    X = X.loc[:, X.notna().any(axis=0)]
    # drop rows with any NaN
    X_clean = X.dropna(how="any")
    y_clean = y.loc[X_clean.index].astype(float, errors="ignore")
    # drop where y is na or inf
    y_clean = y_clean.replace([np.inf, -np.inf], np.nan).dropna()
    # align again
    X_clean = X_clean.loc[y_clean.index]
    return X_clean, y_clean


def time_train_test_split(X, y, test_pct=0.2):
    n = len(X)
    split_idx = int(n * (1 - test_pct))
    X_train = X.iloc[:split_idx]
    X_test = X.iloc[split_idx:]
    y_train = y.iloc[:split_idx]
    y_test = y.iloc[split_idx:]
    return X_train, X_test, y_train, y_test


def train_and_save():
    print("Loading features and target from feature_pipeline...")
    # prepare_feature_matrix may accept symbol, timeframe, horizon; adapt call based on your implementation
    # Here we call with symbol and horizon only — adjust if your prepare_feature_matrix signature differs.
    X, y, y_clf, df_full = prepare_feature_matrix(symbol=SYMBOL, horizon=HORIZON)

    if X is None or y is None or X.shape[0] == 0:
        raise RuntimeError("Feature pipeline returned no data. Ensure ingestion and feature pipeline ran correctly.")

    # Clean X, y
    X, y = clean_xy(X, y)
    if len(X) < 200:
        raise RuntimeError(f"Not enough rows after cleaning to train (need >=200, got {len(X)}).")

    # time-series split
    X_train, X_test, y_train, y_test = time_train_test_split(X, y, test_pct=TEST_SIZE_PCT)
    print(f"Train shape: {X_train.shape}, Test shape: {X_test.shape}")

    # Try sklearn LGBMRegressor first (if available)
    tried_sklearn = False
    model_final = None
    best_iter = None
    try:
        tried_sklearn = True
        model = LGBMRegressor(objective="regression", learning_rate=0.05, num_leaves=31,
                              n_estimators=NUM_BOOST_ROUND, random_state=42, verbosity=-1)
        # some builds accept early_stopping_rounds, others do not
        try:
            model.fit(
                X_train, y_train,
                eval_set=[(X_train, y_train), (X_test, y_test)],
                eval_metric="rmse",
                early_stopping_rounds=EARLY_STOPPING_ROUNDS,
                verbose=False
            )
        except TypeError:
            # fallback if this build's sklearn wrapper doesn't accept early_stopping_rounds
            model.fit(X_train, y_train)
        model_final = model
        try:
            best_iter = int(getattr(model, "best_iteration_", None) or getattr(model, "best_iteration", None) or 0)
        except Exception:
            best_iter = None
        print("Trained using sklearn LGBMRegressor.")
    except Exception as e:
        print("sklearn LGBMRegressor failed, falling back to lightgbm.train(). Error:", e)
        tried_sklearn = False

    if not tried_sklearn or model_final is None:
        # Use native LightGBM train API
        print("Training with lightgbm.train() API...")
        params = {
            "objective": "regression",
            "metric": "rmse",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "min_data_in_leaf": 20,
            "verbose": -1
        }
        dtrain = lgb.Dataset(X_train, label=y_train)
        dvalid = lgb.Dataset(X_test, label=y_test, reference=dtrain)
        try:
            booster = lgb.train(
                params,
                dtrain,
                num_boost_round=NUM_BOOST_ROUND,
                valid_sets=[dvalid],
                early_stopping_rounds=EARLY_STOPPING_ROUNDS,
                verbose_eval=False
            )
            print("Trained with early stopping.")
        except TypeError:
            # some builds don't support early stopping API, try without it
            booster = lgb.train(
                params,
                dtrain,
                num_boost_round=NUM_BOOST_ROUND,
                valid_sets=[dvalid],
            )
            print("Trained without early stopping (build doesn't support early_stopping_rounds).")

        model_final = BoosterWrapperTopLevel(booster, features=X.columns)
        try:
            best_iter = int(getattr(booster, "best_iteration", None) or getattr(booster, "current_iteration", None) or 0)
        except Exception:
            best_iter = None

    # Do predictions (use best_iter if available)
    try:
        if isinstance(model_final, BoosterWrapperTopLevel):
            preds_test = model_final.predict(X_test.values)
            preds_train = model_final.predict(X_train.values)
        else:
            # sklearn estimator
            if best_iter and hasattr(model_final, "predict") and hasattr(model_final, "best_iteration_"):
                preds_test = model_final.predict(X_test)
                preds_train = model_final.predict(X_train)
            else:
                preds_test = model_final.predict(X_test)
                preds_train = model_final.predict(X_train)
    except Exception as e:
        raise RuntimeError(f"Prediction on train/test failed: {e}")

    # ensure finite predictions
    if not np.isfinite(preds_test).all():
        raise RuntimeError("Predictions contain NaN/inf; aborting.")

    # metrics
    mse = float(mean_squared_error(y_test, preds_test))
    mae = float(mean_absolute_error(y_test, preds_test))
    r2 = float(r2_score(y_test, preds_test))
    preds_test_bin = (np.array(preds_test) > 0).astype(int)
    y_clf_test = (y_test > 0).astype(int)
    acc = float(accuracy_score(y_clf_test, preds_test_bin))
    f1 = float(f1_score(y_clf_test, preds_test_bin))

    print("Test MSE:", mse)
    print("Test MAE:", mae)
    print("Test R2:", r2)
    print("Test Accuracy (up/down):", acc, "F1:", f1)

    # Save artifacts:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    # Save native booster if we have an lgb.Booster inside wrapper
    booster_file = MODEL_DIR / f"lgb_booster_{SYMBOL.replace('/','_')}_{ts}.txt"
    joblib_file = MODEL_DIR / f"lgb_model_{SYMBOL.replace('/','_')}_{ts}.joblib"
    metadata_file = MODEL_DIR / f"metadata_{SYMBOL.replace('/','_')}_{ts}.json"

    # If sklearn model_final is LGBMRegressor, try to extract native booster (if available)
    try:
        if hasattr(model_final, "booster_"):  # sklearn LGBMRegressor has booster_
            native_booster = model_final.booster_
            native_booster.save_model(str(booster_file))
            print("Saved native booster:", booster_file)
        elif isinstance(model_final, BoosterWrapperTopLevel):
            # wrapper holds Booster
            model_final.booster.save_model(str(booster_file))
            print("Saved native booster:", booster_file)
    except Exception as e:
        print("Warning: failed to save native booster:", e)

    # Save joblib wrapper: always save a top-level BoosterWrapperTopLevel if booster present
    try:
        if isinstance(model_final, BoosterWrapperTopLevel):
            # joblib dump the wrapper instance (top-level class)
            joblib.dump(model_final, joblib_file)
        else:
            # joblib dump sklearn model (picklable)
            joblib.dump(model_final, joblib_file)
        print("Saved joblib model to:", joblib_file)
    except Exception as e:
        print("Warning: failed to joblib.dump model:", e)

    metadata = {
        "symbol": SYMBOL,
        "timeframe": "1h",
        "horizon_hours": HORIZON,
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "mse": mse,
        "mae": mae,
        "r2": r2,
        "accuracy_updown": acc,
        "f1_updown": f1,
        "model_file": joblib_file.name,
        "booster_file": booster_file.name if booster_file.exists() else None,
        "features": list(X.columns),
        "trained_at_utc": ts,
        "used_api": "sklearn_lgbm" if tried_sklearn else "lgb_train"
    }
    metadata_file.write_text(json.dumps(metadata, indent=2))
    print("Saved metadata to:", metadata_file)

    # write latest.json that the API loader expects
    latest_path = MODEL_DIR / "latest.json"
    latest_path.write_text(json.dumps({
        "model_file": joblib_file.name,
        "booster_file": booster_file.name if booster_file.exists() else None,
        "features": list(X.columns)
    }, indent=2))
    print("Wrote latest.json ->", latest_path)

    return model_final, metadata


if __name__ == "__main__":
    model, meta = train_and_save()
    print("✅ Training complete. Metadata:", meta)
