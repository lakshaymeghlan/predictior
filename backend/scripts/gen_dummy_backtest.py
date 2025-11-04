# backend/scripts/gen_dummy_backtest.py
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
import os, sys

BASE_DIR = Path(__file__).resolve().parents[1]  # backend/
MODEL_DIR = Path(os.getenv("MODEL_DIR", BASE_DIR / "models")).resolve()
BACK = MODEL_DIR / "backtests"

BACK.mkdir(parents=True, exist_ok=True)

def create_for(symbol="BTC_USDT"):
    x = np.arange(0, 200)
    y = 1000 + np.cumsum(np.random.randn(200).cumsum()*0.5)
    plt.figure(figsize=(7,3))
    plt.plot(x, y)
    plt.title(f"Equity curve {symbol.replace('_','/')}")
    plt.tight_layout()
    out = BACK / f"equity_{symbol}.png"
    plt.savefig(out, dpi=120)
    plt.close()
    print("Wrote", out)

if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTC_USDT"
    create_for(sym)
