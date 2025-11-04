# backend/model_registry.py
import json
import glob
import os
from typing import Optional, Dict
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
# models live under backend/models (based on your project structure screenshots)
MODELS_DIR = (THIS_DIR / "models").resolve()

def _normalize_symbol_for_filename(symbol: str) -> str:
    if not symbol:
        return symbol
    s = symbol.replace("/", "_").replace("-", "_").upper()
    return s

def find_latest_metadata(symbol: str, timeframe: str) -> Optional[Dict]:
    """
    Find latest metadata json for a given symbol/timeframe.
    returns parsed JSON dict with added key "_meta_path" pointing to the file.
    """
    if not symbol:
        return None
    sym = _normalize_symbol_for_filename(symbol)
    tf = (timeframe or "").lower()

    # Prefer metadata files with both symbol and timeframe in name (e.g. metadata_ETH_USDT_1h_...)
    patterns = [
        str(MODELS_DIR / f"metadata_{sym}*{tf}*.json"),
        str(MODELS_DIR / f"metadata_{sym}_*.json"),
        str(MODELS_DIR / f"*{sym}*.json"),
    ]
    files = []
    for p in patterns:
        files = glob.glob(p)
        if files:
            break
    if not files:
        return None

    # choose latest by modified time
    latest = max(files, key=lambda p: os.path.getmtime(p))
    try:
        with open(latest, "r") as f:
            meta = json.load(f)
    except Exception:
        return None
    meta["_meta_path"] = str(Path(latest).resolve())
    # normalize expected keys
    if "symbol" not in meta:
        meta["symbol"] = sym
    if "timeframe" not in meta:
        meta["timeframe"] = tf
    return meta

def get_model_path_from_meta(meta: Dict) -> Optional[str]:
    """
    meta could contain keys like 'model_file', 'model_path', 'booster_file', 'artifact' or 'model_name'.
    Return an absolute path if found, else None.
    """
    if not meta:
        return None
    candidate_keys = ["model_file", "model_path", "booster_file", "artifact", "model"]
    for k in candidate_keys:
        val = meta.get(k)
        if not val:
            continue
        p = Path(val)
        if not p.is_absolute():
            p = MODELS_DIR / p
        if p.exists():
            return str(p.resolve())

    # try model_name
    if "model_name" in meta:
        p = MODELS_DIR / meta["model_name"]
        if p.exists():
            return str(p.resolve())

    # try to discover a joblib or lgb file that includes the meta filename timestamp as substring
    meta_path = meta.get("_meta_path")
    if meta_path:
        meta_basename = Path(meta_path).stem  # e.g., metadata_BTC_USDT_20251023_194711
        for ext in (".joblib", ".pkl", ".txt", ".model"):
            candidates = list(MODELS_DIR.glob(f"*{meta_basename}*{ext}"))
            if candidates:
                return str(candidates[0].resolve())

    # final fallback: newest lgb/text or joblib in models dir
    all_candidates = (
        list(MODELS_DIR.glob("*.txt"))
        + list(MODELS_DIR.glob("*.joblib"))
        + list(MODELS_DIR.glob("*.pkl"))
        + list(MODELS_DIR.glob("*.model"))
    )
    if all_candidates:
        best = max(all_candidates, key=lambda p: p.stat().st_mtime)
        return str(best.resolve())

    return None
