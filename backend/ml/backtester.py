"""
Backtester (robust model loading + safer defaults).
Place in predictor/backend/ml/backtester.py
"""
import os
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
import importlib
import sys
import types
import lightgbm as lgb

from feature_pipeline import prepare_feature_matrix
from dotenv import load_dotenv

load_dotenv()

MODEL_DIR = Path(os.getenv("MODEL_DIR", "../models")).resolve()
RESULTS_DIR = MODEL_DIR / "backtests"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Safer backtest config
CONFIG = {
    "symbol": os.getenv("SYMBOL", "BTC/USDT"),
    "horizon": 1,
    "initial_capital": 10000.0,
    "position_sizing": "fractional",
    "fraction_per_trade": 0.005,    # safer default: 0.5% per trade
    "fixed_position_usd": 100.0,
    "fee_pct": 0.001,
    "slippage_abs_pct": 0.0005,
    "min_trade_usd": 5.0,
    "signal_threshold": 0.00075,    # only act on predictions > 0.075%
    "allow_short": False,
    "execution": "next_open",
    "verbose": True,
    "min_hold_hours": 3,
    "top_k_pct": None,
    "max_trades_per_day": 10,
}

def diagnostics(preds: pd.Series, df_full: pd.DataFrame, horizon=1):
    target_col = f"next_{horizon}h_return"
    if target_col not in df_full.columns:
        print("Diagnostics: target column not found in df_full.")
        return
    actual = df_full[target_col].loc[preds.index]
    corr = preds.corr(actual)
    pred_bin = (preds > 0).astype(int)
    actual_bin = (actual > 0).astype(int)
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    acc = accuracy_score(actual_bin, pred_bin)
    prec = precision_score(actual_bin, pred_bin, zero_division=0)
    rec = recall_score(actual_bin, pred_bin, zero_division=0)
    f1 = f1_score(actual_bin, pred_bin, zero_division=0)

    print("=== Model diagnostics ===")
    print(f"Rows evaluated: {len(preds)}")
    print(f"Pearson corr(pred, actual): {corr:.6f}")
    print(f"Up/down accuracy: {acc:.4f}, precision: {prec:.4f}, recall: {rec:.4f}, f1: {f1:.4f}")
    print("Preds pctiles:", preds.quantile([0.01,0.05,0.25,0.5,0.75,0.95,0.99]).to_dict())
    print("Actual pctiles:", actual.quantile([0.01,0.05,0.25,0.5,0.75,0.95,0.99]).to_dict())

def generate_signals_advanced(preds: pd.Series, df_full: pd.DataFrame, cfg=CONFIG):
    threshold = float(cfg.get("signal_threshold", 0.0))
    min_hold = int(cfg.get("min_hold_hours", 0))
    top_k_pct = cfg.get("top_k_pct", None)
    allow_short = bool(cfg.get("allow_short", False))
    max_trades_per_day = cfg.get("max_trades_per_day", None)

    idx = preds.index
    signals = pd.Series(0, index=idx, dtype=int)

    if top_k_pct is not None:
        k = float(top_k_pct)
        if not (0 < k < 1):
            raise ValueError("top_k_pct must be between 0 and 1")
        hi_cut = preds.quantile(1.0 - k)
        lo_cut = preds.quantile(k)
    else:
        hi_cut = None
        lo_cut = None

    last_signal = 0
    hold_counter = 0
    trades_today = 0
    last_day = None

    for i, t in enumerate(idx):
        day = t.floor("D")
        if last_day is None or day != last_day:
            trades_today = 0
            last_day = day

        p = preds.iloc[i]
        desired = 0
        if top_k_pct is not None:
            if p >= hi_cut:
                desired = 1
            elif allow_short and p <= lo_cut:
                desired = -1
        else:
            if p >= threshold:
                desired = 1
            elif allow_short and p <= -threshold:
                desired = -1

        if last_signal != 0 and hold_counter < min_hold:
            desired = last_signal
            hold_counter += 1
        else:
            if desired != last_signal:
                hold_counter = 1 if desired != 0 else 0

        will_trade = (desired != last_signal)
        if will_trade and max_trades_per_day is not None and trades_today >= max_trades_per_day:
            desired = last_signal
        if will_trade and desired != last_signal and desired != 0:
            trades_today += 1

        signals.iloc[i] = desired
        last_signal = desired

    return signals

def load_latest_model():
    latest = MODEL_DIR / "latest.json"
    if not latest.exists():
        raise FileNotFoundError("latest.json not found. Run training first.")
    with open(latest, "r") as f:
        info = json.load(f)

    # prefer native booster if present
    booster_file = info.get("booster_model", None) or info.get("booster_file", None)
    joblib_file = info.get("joblib_model") or info.get("model_file")

    if booster_file:
        try:
            booster = lgb.Booster(model_file=str(booster_file))
            class SimpleBoosterWrap:
                def __init__(self, b): self.booster = b
                def predict(self, X, num_iteration=None):
                    if num_iteration is None:
                        return self.booster.predict(X)
                    return self.booster.predict(X, num_iteration=num_iteration)
            return SimpleBoosterWrap(booster), info["features"]
        except Exception as e:
            print("Failed to load native booster:", e)

    if joblib_file:
        try:
            model = joblib.load(joblib_file)
            return model, info["features"]
        except Exception as e:
            print("joblib.load failed:", e)

    # If joblib fails because class was pickled from train script as __main__.BoosterWrapper,
    # try importing train_lightgbm and inject BoosterWrapper into __main__
    try:
        mod = None
        try:
            mod = importlib.import_module("train_lightgbm")
        except Exception:
            from importlib.machinery import SourceFileLoader
            tl_path = (Path(__file__).resolve().parents[0] / "train_lightgbm.py").resolve()
            if tl_path.exists():
                loader = SourceFileLoader("train_lightgbm", str(tl_path))
                mod = types.ModuleType(loader.name)
                loader.exec_module(mod)
                sys.modules["train_lightgbm"] = mod

        if mod is not None and hasattr(mod, "BoosterWrapper"):
            main_mod = sys.modules.get("__main__")
            if main_mod is None:
                main_mod = types.ModuleType("__main__")
                sys.modules["__main__"] = main_mod
            setattr(sys.modules["__main__"], "BoosterWrapper", getattr(mod, "BoosterWrapper"))
            # retry joblib.load
            model = joblib.load(joblib_file)
            return model, info["features"]
    except Exception as e2:
        print("Retry inject BoosterWrapper failed:", e2)

    raise RuntimeError(f"Unable to load model. Check latest.json at {latest}")

def compute_predictions(model, features, X):
    missing = [c for c in features if c not in X.columns]
    if missing:
        raise ValueError(f"Feature mismatch: missing columns: {missing}")
    Xf = X[features].copy()
    try:
        preds = model.predict(Xf)
    except TypeError:
        preds = model.predict(Xf, num_iteration=None)
    preds = pd.Series(preds, index=Xf.index, name="pred")
    return preds

def run_backtest(df_prices, signals, cfg=CONFIG):
    cfg = cfg.copy()
    init_cap = cfg["initial_capital"]
    fee = float(cfg["fee_pct"])
    slippage = float(cfg["slippage_abs_pct"])
    frac = float(cfg["fraction_per_trade"])
    fixed_usd = float(cfg["fixed_position_usd"])
    allow_short = bool(cfg["allow_short"])
    min_trade_usd = float(cfg["min_trade_usd"])

    idx = df_prices.index
    trades = []
    equity = init_cap
    equity_curve = []
    position = 0.0
    cash = equity
    entry_price = None
    last_signal = 0

    for i in range(len(idx) - 1):
        ts = idx[i]
        next_ts = idx[i + 1]
        close_price = float(df_prices["close"].iloc[i])
        open_next = float(df_prices["open"].iloc[i + 1])

        signal_now = int(signals.iloc[i])
        if signal_now != last_signal:
            if cfg["position_sizing"] == "fractional":
                target_usd = equity * frac
            else:
                target_usd = fixed_usd

            size_units = 0.0
            if target_usd >= min_trade_usd:
                size_units = target_usd / open_next

            exec_price = open_next * (1.0 + slippage * (1 if signal_now >= 0 else -1))

            if position != 0:
                close_units = position
                pnl = close_units * (exec_price - entry_price) if position > 0 else close_units * (entry_price - exec_price)
                fee_exit = abs(close_units * exec_price) * fee
                cash += pnl - fee_exit
                trades.append({
                    "ts": next_ts,
                    "action": "close",
                    "units": close_units,
                    "price": exec_price,
                    "pnl": pnl,
                    "fee": fee_exit,
                    "equity": cash
                })
                position = 0.0
                entry_price = None

            if signal_now != 0:
                if signal_now == 1:
                    position = size_units
                    entry_price = exec_price
                    fee_entry = abs(size_units * exec_price) * fee
                    cash -= size_units * exec_price + fee_entry
                    trades.append({
                        "ts": next_ts,
                        "action": "open_long",
                        "units": size_units,
                        "price": exec_price,
                        "fee": fee_entry,
                        "equity": cash + position * close_price
                    })
                elif signal_now == -1 and allow_short:
                    position = -size_units
                    entry_price = exec_price
                    cash += size_units * exec_price - (abs(size_units * exec_price) * fee)
                    trades.append({
                        "ts": next_ts,
                        "action": "open_short",
                        "units": -size_units,
                        "price": exec_price,
                        "fee": abs(size_units * exec_price) * fee,
                        "equity": cash + position * close_price
                    })
                else:
                    pass

            last_signal = signal_now

        mtm = cash + position * close_price
        equity = mtm
        equity_curve.append({"ts": ts, "equity": mtm, "cash": cash, "position": position, "close": close_price})

    final_close = float(df_prices["close"].iloc[-1])
    final_mtm = cash + position * final_close
    equity_curve.append({"ts": idx[-1], "equity": final_mtm, "cash": cash, "position": position, "close": final_close})

    eq_df = pd.DataFrame(equity_curve).set_index("ts")
    eq_df.index = pd.to_datetime(eq_df.index).tz_localize("UTC") if eq_df.index.tz is None else eq_df.index
    trades_df = pd.DataFrame(trades)

    return eq_df, trades_df

def performance_metrics(equity_series):
    eq = equity_series.copy()
    returns = eq.pct_change().fillna(0)
    ann_factor = 24 * 365
    total_return = eq.iloc[-1] / eq.iloc[0] - 1.0 if eq.iloc[0] > 0 else np.nan
    n_years = (eq.index[-1] - eq.index[0]).total_seconds() / (365 * 24 * 3600)
    if eq.iloc[0] > 0 and eq.iloc[-1] > 0 and n_years > 0:
        cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / n_years) - 1
    else:
        cagr = np.nan
    ann_vol = returns.std() * np.sqrt(ann_factor)
    sharpe = (returns.mean() * ann_factor) / (returns.std() * np.sqrt(ann_factor) + 1e-9)
    neg_rets = returns[returns < 0]
    downside = neg_rets.std() * np.sqrt(ann_factor) if len(neg_rets) > 0 else np.nan
    sortino = (returns.mean() * ann_factor) / (downside + 1e-9) if downside is not np.nan else np.nan
    cum_max = eq.cummax()
    drawdown = (eq - cum_max) / cum_max
    max_dd = drawdown.min()
    stats = {
        "total_return": float(total_return) if not np.isnan(total_return) else None,
        "cagr": float(cagr) if not np.isnan(cagr) else None,
        "annualized_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "sortino": float(sortino) if sortino is not None else None,
        "max_drawdown": float(max_dd),
        "start": str(eq.index[0]),
        "end": str(eq.index[-1])
    }
    return stats

def run_and_report(cfg=CONFIG, save_outputs=True):
    X, y, y_clf, df_full = prepare_feature_matrix(horizon=cfg["horizon"])
    model, features = load_latest_model()
    preds = compute_predictions(model, features, X)
    preds = preds.loc[df_full.index]

    # diagnostics printout
    diagnostics(preds, df_full, horizon=cfg["horizon"])

    signals = generate_signals_advanced(preds, df_full, cfg=cfg)
    eq_df, trades_df = run_backtest(df_full, signals, cfg=cfg)
    stats = performance_metrics(eq_df["equity"])

    stats["num_trades"] = len(trades_df)
    if len(trades_df) > 0 and "pnl" in trades_df.columns:
        wins = trades_df[trades_df["pnl"] > 0]
        stats["win_rate"] = float(len(wins) / len(trades_df))
        stats["avg_trade_pnl"] = float(trades_df["pnl"].mean())
    else:
        stats["win_rate"] = None
        stats["avg_trade_pnl"] = None

    print("=== Backtest summary ===")
    for k, v in stats.items():
        print(f"{k}: {v}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if save_outputs:
        out_eq = RESULTS_DIR / f"equity_{cfg['symbol'].replace('/','_')}_{ts}.csv"
        eq_df.to_csv(out_eq)
        out_trades = RESULTS_DIR / f"trades_{cfg['symbol'].replace('/','_')}_{ts}.csv"
        trades_df.to_csv(out_trades, index=False)
        print("Saved equity curve to:", out_eq)
        print("Saved trades to:", out_trades)
        try:
            import matplotlib.pyplot as plt
            plt.figure(figsize=(10,5))
            plt.plot(eq_df.index, eq_df["equity"])
            plt.title(f"Equity curve {cfg['symbol']}")
            plt.ylabel("Equity (USD)")
            plt.xlabel("Time")
            plt.grid(True)
            out_png = RESULTS_DIR / f"equity_{cfg['symbol'].replace('/','_')}_{ts}.png"
            plt.savefig(out_png, bbox_inches="tight", dpi=150)
            plt.close()
            print("Saved equity plot to:", out_png)
        except Exception as e:
            print("Plotting failed:", e)

    return eq_df, trades_df, stats

if __name__ == "__main__":
    eq, trades, stats = run_and_report()
