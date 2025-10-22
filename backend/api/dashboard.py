# predictor/backend/api/dashboard.py
from fastapi import APIRouter, Depends
from .auth import get_current_user
from .db import SessionLocal
from pathlib import Path
import os, json

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
MODEL_DIR = Path(os.getenv("MODEL_DIR", "../models")).resolve()

@router.get("/me")
def my_dashboard(user = Depends(get_current_user)):
    models = []
    try:
        for p in MODEL_DIR.glob("*"):
            if p.is_file() and p.suffix in (".joblib", ".txt", ".json"):
                models.append(p.name)
    except Exception:
        models = []
    alerts = []
    try:
        alerts = json.loads(user.metadata_json or "{}").get("alerts", [])
    except Exception:
        alerts = []
    return {
        "email": user.email,
        "created_at": str(user.created_at),
        "quota_daily": user.quota_daily,
        "quota_remaining": user.quota_remaining,
        "quota_reset_at": str(user.quota_reset_at) if user.quota_reset_at else None,
        "models_available": models,
        "alerts": alerts
    }
