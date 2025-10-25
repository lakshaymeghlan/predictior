# backend/api/quota.py
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone, timedelta
import os

router = APIRouter(prefix="/quota", tags=["quota"])
DEFAULT_QUOTA = int(os.getenv("DEFAULT_QUOTA", "100"))

@router.get("/status")
def quota_status():
    # dev-only simple status (replace with DB-backed in production)
    return {"quota_default": DEFAULT_QUOTA, "note": "Per-user quota requires DB-backed user object. Use /dashboard/me to view real quota."}

def consume_quota(required: int = 1):
    """
    Returns a dependency to be combined with your get_current_user.
    Example: user = Depends(consume_quota(1))
    In this minimal stub we just allow all requests (development).
    Replace with DB-backed logic if you have `User` model.
    """
    def dep(user=Depends(lambda: None)):
        # For now, simply return user (real implementation should decrement and persist)
        if user is None:
            raise HTTPException(status_code=401, detail="Unauthorized")
        # production: check and decrement user.quota_remaining
        return user
    return dep
