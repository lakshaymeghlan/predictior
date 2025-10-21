"""
paper_trader.py

Simple paper trading / simulator runner.

Usage:
  # Simulation run (no API keys required)
  PY_ENV=dev PYTHONPATH=./backend python backend/paper_trader.py

  # Real exchange testnet run (only if you created testnet keys and set env vars)
  CCXT_EXCHANGE=binance TESTNET=true API_KEY=... API_SECRET=... PAPER_MODE=live python backend/paper_trader.py

Design:
 - Safe-by-default: PAPER_MODE defaults to "simulate". Only attempts CCXT orders when PAPER_MODE="live".
 - Uses your existing backend/ml/feature_pipeline.prepare_feature_matrix to compute latest features.
 - Loads model using the same loader logic as your API (we import the loader from api.app or re-implement small loader).
 - Records trades to models/paper_trades_{timestamp}.csv and (optionally) a Postgres table 'paper_trades' if PG_URI available.

Important:
 - Test the CCXT live mode only on exchange testnets (Binance testnet, or any exchange that offers sandbox).
 - Amount semantics differ between exchanges: for spot market, CCXT create_order(symbol, type, side, amount) expects amount in base currency for many exchanges.
 - This code is for paper trading / research — do not use in production with real money without additional safety & rate limiting.
"""

import os
import time
import math
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import numpy as np
import joblib
import ccxt
from dotenv import load_dotenv

# Ensure backend/ml is importable for feature pipeline and model loading
REPO_ROOT = Path(__file__).resolve().parents[1]  # predictor/backend -> up 1 -> predictor
ML_PATH = REPO_ROOT / "backend" / "ml"
if str(ML_PATH) not in os.sys.path:
    os.sys.path.insert(0, str(ML_PATH))

# import feature pipeline & model loader from your api or ml
try:
    from feature_pipeline import prepare_feature_matrix
except Exception as e:
    raise RuntimeError("feature_pipeline import failed; ensure backend/ml is present and PG_URI env set: " + str(e))

# Optionally import a robust model loader from api.app (if you kept it there)
# We'll implement a small loader here that mirrors earlier logic: prefer native booster file, fallback joblib
def load_latest_model_local(model_dir: Path):
    """
    Robust loader: try given model_dir; if empty or missing, search common locations under repo for model artifacts.
    Returns dict: {"type":"booster"|"joblib", "model": <obj>, "features": [...], "version": "<filename>"}
    """
    import lightgbm as lgb

    def try_load_from_path(p: Path, features_list=None):
        p = p.resolve()
        if not p.exists():
            raise FileNotFoundError(f"Model file not found: {p}")
        if p.suffix in [".txt", ".model"]:
            booster = lgb.Booster(model_file=str(p))
            return {"type": "booster", "model": booster, "features": features_list or [], "version": p.name}
        if p.suffix in [".joblib", ".pkl"]:
            mdl = joblib.load(str(p))
            return {"type": "joblib", "model": mdl, "features": features_list or [], "version": p.name}
        # fallback: try load as booster then joblib
        try:
            booster = lgb.Booster(model_file=str(p))
            return {"type": "booster", "model": booster, "features": features_list or [], "version": p.name}
        except Exception:
            mdl = joblib.load(str(p))
            return {"type": "joblib", "model": mdl, "features": features_list or [], "version": p.name}

    # 1) Try explicit latest.json in model_dir
    latest_json = model_dir / "latest.json"
    if latest_json.exists():
        try:
            info = json.loads(latest_json.read_text())
            mf = info.get("model_file") or info.get("booster_file") or info.get("model_path") or info.get("model")
            features = info.get("features") or info.get("feature_list") or []
            if mf:
                p = Path(mf)
                if not p.is_absolute():
                    p = model_dir / p
                try:
                    return try_load_from_path(p, features)
                except Exception:
                    pass
        except Exception:
            pass

    # 2) Try scanning provided model_dir for artifacts
    if model_dir.exists():
        boosters = sorted(model_dir.glob("lgb_booster_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        joblibs = sorted(model_dir.glob("lgb_model_*.joblib"), key=lambda p: p.stat().st_mtime, reverse=True)
        if boosters:
            return try_load_from_path(boosters[0], [])
        if joblibs:
            return try_load_from_path(joblibs[0], [])

    # 3) Try common fallback locations relative to repo root
    repo_root = Path(__file__).resolve().parents[1]  # predictor/backend -> up 1 -> predictor
    candidates = [
        repo_root / "backend" / "models",
        repo_root / "models",
        repo_root / "backend" / "ml" / ".." / "models",
        repo_root / "backend" / "ml" / "../models",
    ]
    for cand in candidates:
        cand = cand.resolve()
        boosters = sorted(Path(cand).glob("lgb_booster_*.txt") if Path(cand).exists() else [], key=lambda p: p.stat().st_mtime, reverse=True)
        joblibs = sorted(Path(cand).glob("lgb_model_*.joblib") if Path(cand).exists() else [], key=lambda p: p.stat().st_mtime, reverse=True)
        if boosters:
            return try_load_from_path(boosters[0], [])
        if joblibs:
            return try_load_from_path(joblibs[0], [])

    # 4) final scan across repo for model artifacts
    search_paths = list(Path(__file__).resolve().parents[2].glob("**/lgb_booster_*.txt")) + list(Path(__file__).resolve().parents[2].glob("**/lgb_model_*.joblib"))
    if search_paths:
        # sort by mtime
        search_paths = sorted(search_paths, key=lambda p: p.stat().st_mtime, reverse=True)
        for p in search_paths:
            try:
                return try_load_from_path(p, [])
            except Exception:
                continue

    raise RuntimeError("No model artifact found in given MODEL_DIR or common fallback locations. Please run training (train_lightgbm.py) to produce artifacts or set MODEL_DIR appropriately.")


# CONFIG via env
load_dotenv()  # loads .env if present
MODEL_DIR = Path(os.getenv("MODEL_DIR", "../models")).resolve()
OUTPUT_DIR = MODEL_DIR / "paper_trades"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PAPER_MODE = os.getenv("PAPER_MODE", "simulate").lower()   # simulate | live
CCXT_EXCHANGE = os.getenv("CCXT_EXCHANGE", "binance")
TESTNET_FLAG = os.getenv("TESTNET", "true").lower() in ("1","true","yes")
API_KEY = os.getenv("API_KEY", None)
API_SECRET = os.getenv("API_SECRET", None)

SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
POSITION_FRAC = float(os.getenv("POSITION_FRAC", "0.01"))  # fraction of equity to allocate per trade
INITIAL_CAP = float(os.getenv("INITIAL_CAP", "10000.0"))
FEE_PCT = float(os.getenv("FEE_PCT", "0.001"))
SLIPPAGE_PCT = float(os.getenv("SLIPPAGE_PCT", "0.0005"))
SIGNAL_THRESHOLD = float(os.getenv("SIGNAL_THRESHOLD", "0.0005"))  # same as backtest sensible default
MIN_HOLD = int(os.getenv("MIN_HOLD", "3"))  # hours to hold

SLEEP_SECS = int(os.getenv("SLEEP_SECS", "300"))  # default 5 minutes between loop runs

# safety checks
if PAPER_MODE not in ("simulate", "live"):
    print("Invalid PAPER_MODE, defaulting to simulate.")
    PAPER_MODE = "simulate"

# ccxt exchange factory (only used when PAPER_MODE == 'live')
def make_exchange():
    exch_name = CCXT_EXCHANGE
    ex = getattr(ccxt, exch_name)({
        "apiKey": API_KEY,
        "secret": API_SECRET,
        "enableRateLimit": True,
    })
    # special case: many exchanges offer a testnet endpoint. For Binance set 'test' or 'urls' field
    if exch_name == "binance" and TESTNET_FLAG:
        # switch to testnet endpoints if available
        ex.set_sandbox_mode(True)
    return ex


# Simple order record structure
def record_trade(d: dict, out_dir=OUTPUT_DIR):
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    p = out_dir / f"paper_trades_{ts}.csv"
    df = pd.DataFrame([d])
    if p.exists():
        df.to_csv(p, mode="a", header=False, index=False)
    else:
        df.to_csv(p, index=False)
    print("Recorded trade:", d)
    return p


# Lightweight state keeper to track position & last_signal across runs (persist to file)
STATE_FILE = OUTPUT_DIR / "paper_state.json"
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"position": 0.0, "entry_price": None, "last_signal": 0, "equity": INITIAL_CAP, "cash": INITIAL_CAP, "last_ts": None}

def save_state(st):
    STATE_FILE.write_text(json.dumps(st))


# Signal logic (same rules as backtester basic)
def decide_signal(pred_value, threshold=SIGNAL_THRESHOLD):
    if pred_value >= threshold:
        return 1
    if pred_value <= -threshold:
        return -1
    return 0


def main_loop():
    print("Paper trader starting. Mode:", PAPER_MODE)
    model_info = load_latest_model_local(MODEL_DIR)
    print("Loaded model:", model_info["version"])

    state = load_state()

    while True:
        try:
            # compute latest features & get prediction
            X, y, y_clf, df_full = prepare_feature_matrix(SYMBOL, horizon=1)
            if X.empty:
                print("No features available yet, sleeping.")
                time.sleep(SLEEP_SECS)
                continue

            last_row = X.iloc[-1]
            # align features to model if model_info has features (optional)
            # we'll try to call model predict robustly
            if model_info["type"] == "booster":
                import lightgbm as lgb
                feat_order = model_info.get("features") or list(X.columns)
                row_df = last_row.reindex(feat_order).fillna(0.0).to_frame().T
                pred = model_info["model"].predict(row_df.values)[0]
            else:
                feat_order = model_info.get("features") or list(X.columns)
                row_df = last_row.reindex(feat_order).fillna(0.0).to_frame().T
                try:
                    pred = model_info["model"].predict(row_df)[0]
                except TypeError:
                    pred = model_info["model"].predict(row_df, num_iteration=None)[0]

            # decide signal
            signal = decide_signal(pred, threshold=SIGNAL_THRESHOLD)

            ts = df_full.index[-1]
            print(f"[{ts}] pred={pred:.6f} signal={signal} state_last={state['last_signal']} equity={state['equity']:.2f}")

            # enforce min_hold: if we are in position and haven't held min_hold periods, skip flip
            if state["last_signal"] != 0 and state.get("hold_count", 0) < MIN_HOLD:
                print("Holding due to min_hold. incrementing counter.")
                state["hold_count"] = state.get("hold_count", 0) + 1
                save_state(state)
                time.sleep(SLEEP_SECS)
                continue

            # If signal unchanged, do nothing
            if signal == state["last_signal"]:
                # update MTM equity using last close
                last_close = float(df_full["close"].iloc[-1])
                state["equity"] = state["cash"] + state["position"] * last_close
                save_state(state)
                time.sleep(SLEEP_SECS)
                continue

            # Otherwise, we will close existing and open new if signal != 0
            last_close = float(df_full["close"].iloc[-1])
            exec_price = last_close * (1.0 + SLIPPAGE_PCT * (1 if signal >= 0 else -1))

            # Close existing pos if any
            if state["position"] != 0:
                close_units = state["position"]
                pnl = close_units * (exec_price - state["entry_price"]) if close_units > 0 else close_units * (state["entry_price"] - exec_price)
                fee = abs(close_units * exec_price) * FEE_PCT
                state["cash"] += pnl - fee
                trade_record = {
                    "ts": ts.isoformat(),
                    "action": "close",
                    "units": float(close_units),
                    "price": float(exec_price),
                    "pnl": float(pnl),
                    "fee": float(fee),
                    "equity": float(state["cash"])
                }
                record_trade(trade_record)

                # reset
                state["position"] = 0.0
                state["entry_price"] = None

            # Open new position if signal != 0
            if signal != 0:
                # determine USD allocation
                usd_alloc = state["equity"] * POSITION_FRAC
                units = usd_alloc / exec_price
                if usd_alloc < 1.0:
                    print("Allocation too small, skipping trade.")
                else:
                    # if live mode, place market order via CCXT
                    if PAPER_MODE == "live":
                        try:
                            ex = make_exchange()
                            side = "buy" if signal == 1 else "sell"
                            # amount semantics vary: for spot markets many exchanges expect amount=base currency units
                            order = ex.create_order(SYMBOL, "market", side, float(units))
                            fill_price = float(order.get("average") or order.get("price") or exec_price)
                            fee_paid = 0.0
                            # Try to extract fee info
                            if "fee" in order:
                                fee_paid = float(order["fee"].get("cost", 0.0))
                            # Update state: for long we spent funds; for short simplified handling not implemented
                            if signal == 1:
                                state["position"] = units
                                state["entry_price"] = fill_price
                                state["cash"] -= units * fill_price + fee_paid
                            else:
                                # short: treat as negative position; simplified approach
                                state["position"] = -units
                                state["entry_price"] = fill_price
                                state["cash"] += units * fill_price - fee_paid
                            trade_record = {
                                "ts": ts.isoformat(),
                                "action": f"open_{'long' if signal==1 else 'short'}",
                                "units": float(units if signal==1 else -units),
                                "price": float(fill_price),
                                "fee": float(fee_paid),
                                "equity": float(state["cash"] + state["position"] * last_close)
                            }
                            record_trade(trade_record)
                        except Exception as e:
                            print("Live order failed:", e)
                            # record failure
                            record_trade({"ts": ts.isoformat(), "action": "open_failed", "err": str(e)})
                    else:
                        # simulation: assume exec_price as fill, apply fee
                        fee_paid = abs(units * exec_price) * FEE_PCT
                        if signal == 1:
                            state["position"] = units
                            state["entry_price"] = exec_price
                            state["cash"] -= units * exec_price + fee_paid
                            record_trade({
                                "ts": ts.isoformat(),
                                "action": "open_long_sim",
                                "units": float(units),
                                "price": float(exec_price),
                                "fee": float(fee_paid),
                                "equity": float(state["cash"] + state["position"] * last_close)
                            })
                        else:
                            # short simplified: credit cash on opening
                            state["position"] = -units
                            state["entry_price"] = exec_price
                            state["cash"] += units * exec_price - fee_paid
                            record_trade({
                                "ts": ts.isoformat(),
                                "action": "open_short_sim",
                                "units": float(-units),
                                "price": float(exec_price),
                                "fee": float(fee_paid),
                                "equity": float(state["cash"] + state["position"] * last_close)
                            })

            # Update state fields
            state["last_signal"] = signal
            state["hold_count"] = 1 if signal != 0 else 0
            state["last_ts"] = ts.isoformat()
            # recompute equity mark-to-market
            state["equity"] = state["cash"] + state["position"] * last_close
            save_state(state)

            # Sleep until next check
            time.sleep(SLEEP_SECS)

        except KeyboardInterrupt:
            print("Paper trader interrupted by user. Exiting.")
            break
        except Exception as e:
            print("Paper trader loop error:", e)
            time.sleep(10)


if __name__ == "__main__":
    main_loop()
