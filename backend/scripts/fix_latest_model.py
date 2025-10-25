# scripts/fix_latest_model.py
import json
from pathlib import Path
import argparse

def fix_latest(model_dir: Path):
    model_dir = model_dir.resolve()
    latest_json = model_dir / "latest.json"
    boosters = sorted(model_dir.glob("lgb_booster_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    joblibs = sorted(model_dir.glob("lgb_model_*.joblib"), key=lambda p: p.stat().st_mtime, reverse=True)
    metas = sorted(model_dir.glob("metadata_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    info = {}
    if latest_json.exists():
        try:
            info = json.loads(latest_json.read_text())
        except Exception:
            info = {}

    # try to reuse metadata features if available
    features = None
    if metas:
        try:
            mj = json.loads(metas[0].read_text())
            features = mj.get("features") or features
        except Exception:
            pass

    if boosters:
        info["booster_file"] = boosters[0].name
    if joblibs:
        info["model_file"] = joblibs[0].name
    if features:
        info["features"] = features

    if not boosters and not joblibs:
        raise SystemExit(f"No model artifacts found in {model_dir}. Run training first.")

    latest_json.write_text(json.dumps(info, indent=2))
    print("Wrote latest.json ->", latest_json)
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", default="backend/models", help="Path to MODEL_DIR (relative or absolute)")
    args = p.parse_args()
    fix_latest(Path(args.model_dir))
