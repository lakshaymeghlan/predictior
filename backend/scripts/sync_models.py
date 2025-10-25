# backend/scripts/sync_models.py
import shutil, json
from pathlib import Path

SRC = Path.cwd() / "backend" / "models"   # where training wrote artifacts
DST = Path.cwd() / "backend" / "models"   # same - adjust if needed

# If your training wrote to a different folder, copy files into DST
# This simple script ensures latest.json references are correct relative to DST
def sync():
    src = SRC
    dst = DST
    dst.mkdir(parents=True, exist_ok=True)
    # copy relevant files
    for pat in ["lgb_booster_*.txt", "lgb_model_*.joblib", "metadata_*.json", "latest.json"]:
        for f in src.glob(pat):
            shutil.copy2(f, dst / f.name)
    # if latest.json present and has relative names, ensure files exist
    latest = dst / "latest.json"
    if latest.exists():
        info = json.loads(latest.read_text())
        for k in ("model_file","booster_file","model_path"):
            if k in info:
                p = Path(info[k])
                if not p.is_absolute() and not (dst / p.name).exists():
                    # try to find a same-prefix file
                    found = list(dst.glob("*" + p.name.split(".")[0] + "*"))
                    if found:
                        info[k] = found[0].name
        latest.write_text(json.dumps(info, indent=2))
    print("Synced model artifacts to", dst)

if __name__ == "__main__":
    sync()
