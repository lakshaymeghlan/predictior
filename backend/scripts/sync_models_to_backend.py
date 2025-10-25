# backend/scripts/sync_models_to_backend.py
"""
Safe sync script: populates DST_DIR/latest.json with model filenames.
If copying a file fails due to permission (locked), we still reference the
existing filename so downstream code can use it.

Usage:
    python sync_models_to_backend.py SRC_DIR DST_DIR
If omitted, default SRC_DIR=backend/models and DST_DIR=backend/models.
"""
import shutil, json, sys, traceback
from pathlib import Path

SRC_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "models"
DST_DIR = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[2] / "models"
SRC_DIR = SRC_DIR.resolve()
DST_DIR = DST_DIR.resolve()
DST_DIR.mkdir(parents=True, exist_ok=True)

def newest_file(pattern, directory):
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None

booster = newest_file("lgb_booster_*.txt", SRC_DIR)
joblib_f = newest_file("lgb_model_*.joblib", SRC_DIR)
meta = newest_file("metadata_*.json", SRC_DIR)

info = {}
# helper to try copy; on permission error reference original path
def try_copy(src, dst_dir):
    if not src:
        return None
    dst = dst_dir / src.name
    try:
        if src.resolve() == dst.resolve():
            # already same file - nothing to copy
            return dst.name
        shutil.copy2(str(src), str(dst))
        return dst.name
    except PermissionError as e:
        print(f"[WARN] PermissionError copying {src.name} -> {dst}. File in use. Will reference original file name instead.")
        return src.name
    except Exception as e:
        print(f"[WARN] Failed copying {src} -> {dst}: {e}")
        traceback.print_exc()
        # fallback: reference original name
        return src.name

if booster:
    info["booster_file"] = try_copy(booster, DST_DIR)
if joblib_f:
    info["model_file"] = try_copy(joblib_f, DST_DIR)
if meta:
    info["metadata_file"] = try_copy(meta, DST_DIR)
    # try to read features from metadata (prefer DST copy if present)
    try:
        mj_path = DST_DIR / meta.name
        if not mj_path.exists():
            mj_path = meta
        mj = json.loads(mj_path.read_text())
        if "features" in mj:
            info["features"] = mj["features"]
    except Exception as e:
        print("WARN: could not read metadata for features:", e)

latest = DST_DIR / "latest.json"
latest.write_text(json.dumps(info, indent=2))
print("Wrote latest.json ->", latest)
print(json.dumps(info, indent=2))
