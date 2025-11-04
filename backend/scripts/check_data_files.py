# scripts/check_data_files.py
from pathlib import Path
import os
repo_root = Path("E:/predictior/predictior")  # adjust if needed
data_dir = Path(os.getenv("DATA_DIR") or repo_root / "data")
print("DATA_DIR used by script:", data_dir.resolve())
for f in ["ETH_USDT_1h.csv", "BTC_USDT_1h.csv", "GLD_1h.csv", "AAPL_1d.csv"]:
    p = data_dir / f
    print(f, "exists:", p.exists(), " ->", p)
