# backend/api/set_latest_model.py
import json
from pathlib import Path
import os

# read MODEL_DIR from environment or default to repo/models relative to this file
MODEL_DIR = Path(os.getenv("MODEL_DIR", "../models")).resolve()
MODEL_DIR.mkdir(parents=True, exist_ok=True)

def find_latest():
    boosters = sorted(MODEL_DIR.glob("lgb_booster_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    joblibs = sorted(MODEL_DIR.glob("lgb_model_*.joblib"), key=lambda p: p.stat().st_mtime, reverse=True)
    metas = sorted(MODEL_DIR.glob("metadata_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    out = {}
    if boosters:
        out["booster_file"] = boosters[0].name
    if joblibs:
        out["model_file"] = joblibs[0].name
    if metas:
        # try to copy features list if metadata has it
        try:
            mj = json.loads(metas[0].read_text())
            if "features" in mj:
                out["features"] = mj["features"]
        except Exception:
            pass
    if not out:
        raise SystemExit(f"No model files found in {MODEL_DIR}. Run training first.")
    # prefer joblib if both present, but keep both keys
    latest_path = MODEL_DIR / "latest.json"
    latest_path.write_text(json.dumps(out, indent=2))
    print("Wrote latest.json ->", latest_path)
    print("Content:", json.dumps(out, indent=2))
    return out

if __name__ == "__main__":
    find_latest()
