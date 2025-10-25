# backend/scripts/sync_backtests.py
import shutil, json
from pathlib import Path
import os

ROOT = Path.cwd()
# adjust if training wrote to backend/models vs backend/models
SRC_DIRS = [
    ROOT / "backend" / "models",
    ROOT / "models",
]
DST = Path(os.getenv("MODEL_DIR", str(ROOT / "backend" / "models"))) / "backtests"
DST.mkdir(parents=True, exist_ok=True)

patterns = ["equity_*.png", "equity_*.csv", "trades_*.csv"]

found = []
for s in SRC_DIRS:
    if not s.exists(): continue
    for pat in patterns:
        for f in s.glob(pat):
            dest = DST / f.name
            try:
                shutil.copy2(f, dest)
                found.append(dest)
            except Exception as e:
                print("copy failed", f, e)

print("Synced", len(found), "backtest files to", DST)
for f in found[:20]:
    print(" -", f.name)
