# predictor/backend/api/db.py
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

load_dotenv()

# DB URL: prefer PG_URI, then DATABASE_URL, else local SQLite
DB_URL = os.getenv("PG_URI") or os.getenv("DATABASE_URL") or f"sqlite:///{os.path.join(os.getcwd(), 'backend', 'sa.sqlite')}"

# SQLite needs check_same_thread
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}

engine = create_engine(DB_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(256), unique=True, index=True, nullable=False)
    full_name = Column(String(256), nullable=True)
    hashed_password = Column(String(512), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    stripe_customer_id = Column(String(256), nullable=True)
    subscription_status = Column(String(64), nullable=True)  # e.g. active, trialing, past_due
    quota_daily = Column(Integer, default=100)
    quota_remaining = Column(Integer, default=100)
    quota_reset_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(Text, nullable=True)  # renamed to avoid SQLAlchemy reserved name

def init_db():
    Base.metadata.create_all(bind=engine)
