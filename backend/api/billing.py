# predictor/backend/api/billing.py
from fastapi import APIRouter, Depends
from .auth import get_current_user
from .db import SessionLocal
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os, json
try:
    import stripe
except Exception:
    stripe = None

load_dotenv()
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
router = APIRouter(prefix="/billing", tags=["billing"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/subscribe")
def subscribe_plan(plan_id: str, user = Depends(get_current_user), db: Session = Depends(get_db)):
    if STRIPE_API_KEY and stripe:
        stripe.api_key = STRIPE_API_KEY
        if not user.stripe_customer_id:
            cust = stripe.Customer.create(email=user.email, name=user.full_name)
            user.stripe_customer_id = cust["id"]
            db.add(user); db.commit(); db.refresh(user)
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            customer=user.stripe_customer_id,
            line_items=[{"price": plan_id, "quantity": 1}],
            success_url=os.getenv("STRIPE_SUCCESS_URL", "http://localhost:3000/success"),
            cancel_url=os.getenv("STRIPE_CANCEL_URL", "http://localhost:3000/cancel"),
        )
        return {"checkout_url": session.url}
    else:
        user.subscription_status = "active_test"
        db.add(user); db.commit(); db.refresh(user)
        return {"checkout_url": None, "message": "Mock subscription created (STRIPE disabled)"}

@router.get("/status")
def billing_status(user = Depends(get_current_user)):
    return {"email": user.email, "subscription_status": user.subscription_status, "stripe_customer_id": user.stripe_customer_id}
