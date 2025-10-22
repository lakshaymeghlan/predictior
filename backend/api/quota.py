# predictor/backend/api/quota.py
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from .db import SessionLocal
from .auth import get_current_user, User

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def consume_quota(required: int = 1):
    """
    FastAPI dependency: checks if user has enough quota and deducts usage.
    Reuses same DB session to avoid 'attached to different session' errors.
    """
    def _dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        user = db.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")

        now = datetime.utcnow()
        # reset quota if needed
        if not user.quota_reset_at or now >= user.quota_reset_at.replace(tzinfo=None):
            user.quota_remaining = user.quota_daily
            user.quota_reset_at = now + timedelta(days=1)

        if user.quota_remaining < required:
            raise HTTPException(status_code=402, detail="Quota exceeded — upgrade plan")

        user.quota_remaining -= required
        db.commit()
        db.refresh(user)
        return user

    return _dependency
