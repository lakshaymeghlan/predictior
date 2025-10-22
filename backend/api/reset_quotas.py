# predictor/backend/api/reset_quotas.py
from .db import SessionLocal, init_db, User
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()
def reset_all():
    init_db()
    db = SessionLocal()
    users = db.query(User).all()
    for u in users:
        u.quota_remaining = u.quota_daily
        u.quota_reset_at = datetime.now(timezone.utc) + timedelta(days=1)
        db.add(u)
    db.commit()
    db.close()
    print("Reset quotas for", len(users), "users")

if __name__ == "__main__":
    reset_all()
