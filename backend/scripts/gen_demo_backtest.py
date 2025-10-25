# backend/scripts/gen_demo_backtest.py
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
OUT = Path(__file__).resolve().parents[2] / "models" / "backtests"
OUT.mkdir(parents=True, exist_ok=True)

x = np.arange(0, 200)
y = 10000 * np.exp(-0.02 * x) + np.random.randn(len(x)) * 50
plt.figure(figsize=(10,4))
plt.plot(x, y)
plt.title("Equity curve BTC/USDT")
plt.ylabel("Equity (USD)")
plt.tight_layout()
fn = OUT / f"equity_demo.png"
plt.savefig(fn)
print("Wrote demo backtest image:", fn)
