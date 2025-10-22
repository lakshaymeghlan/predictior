# predictor/backend/api/alerts.py
from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel, EmailStr
from .auth import get_current_user
from .db import SessionLocal
from dotenv import load_dotenv
import os, smtplib, json
from email.message import EmailMessage
from sqlalchemy.orm import Session

load_dotenv()
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

router = APIRouter(prefix="/alerts", tags=["alerts"])

class AlertReq(BaseModel):
    title: str
    message: str
    email_to: EmailStr | None = None

def send_email(to_email, subject, body):
    if not SMTP_HOST:
        print("SMTP not configured; skipping send_email")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER or "noreply@example.com"
    msg["To"] = to_email
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        try:
            s.starttls()
            if SMTP_USER and SMTP_PASS:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        except Exception as e:
            print("send_email error:", e)

@router.post("/create")
def create_alert(req: AlertReq, background: BackgroundTasks, user = Depends(get_current_user)):
    db: Session = SessionLocal()
    # reload user in this session
    user_db = db.get(type(user), user.id)
    try:
        meta = json.loads(user_db.metadata_json) if user_db.metadata_json else {}
    except Exception:
        meta = {}
    alerts = meta.get("alerts", [])
    alerts.append({"title": req.title, "message": req.message, "ts": str(__import__("datetime").datetime.utcnow())})
    meta["alerts"] = alerts
    user_db.metadata_json = json.dumps(meta)
    db.add(user_db)
    db.commit()
    db.refresh(user_db)
    db.close()
    to_email = req.email_to or user.email
    background.add_task(send_email, to_email, req.title, req.message)
    return {"status":"created", "email_to": to_email}
