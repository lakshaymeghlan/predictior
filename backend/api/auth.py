# predictor/backend/api/auth.py
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from .db import SessionLocal, init_db, User
from passlib.context import CryptContext
from jose import jwt
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from typing import Generator

load_dotenv()
SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-key")
ALGORITHM = os.getenv("JWT_ALGO", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# Use pbkdf2_sha256 first (no binary deps), bcrypt will be used if installed
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    default="pbkdf2_sha256",
    deprecated="auto"
)

router = APIRouter(prefix="/auth", tags=["auth"])

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Schemas
class RegisterReq(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None

class TokenResp(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str

class LoginReq(BaseModel):
    email: EmailStr
    password: str

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(subject: str | int, expires_delta: timedelta | None = None):
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": str(subject), "exp": int(expire.timestamp())}
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token, expire.isoformat()

@router.post("/register", status_code=201, response_model=TokenResp)
def register(req: RegisterReq, db: Session = Depends(get_db)):
    init_db()
    email = req.email.lower()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = get_password_hash(req.password)
    user = User(
        email=email,
        full_name=req.full_name,
        hashed_password=hashed,
        quota_daily=int(os.getenv("DEFAULT_QUOTA_DAILY", "100")),
        quota_remaining=int(os.getenv("DEFAULT_QUOTA_DAILY", "100")),
        quota_reset_at=datetime.now(timezone.utc) + timedelta(days=1)
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token, exp = create_access_token(user.id)
    return {"access_token": token, "token_type": "bearer", "expires_at": exp}

@router.post("/token", response_model=TokenResp)
def login(req: LoginReq, db: Session = Depends(get_db)):
    init_db()
    user = db.query(User).filter(User.email == req.email.lower()).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token, exp = create_access_token(user.id)
    return {"access_token": token, "token_type": "bearer", "expires_at": exp}

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # 🧭 Normalize datetime comparison (avoid offset-aware vs naive issue)
    now_utc = datetime.utcnow()  # use naive UTC
    reset_at = user.quota_reset_at

    if reset_at is None or now_utc >= reset_at.replace(tzinfo=None):
        user.quota_remaining = user.quota_daily
        user.quota_reset_at = datetime.utcnow() + timedelta(days=1)
        db.add(user)
        db.commit()
        db.refresh(user)

    return user

