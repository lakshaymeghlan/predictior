# predictor/backend/ml/model_registry.py
import sqlite3
from pathlib import Path
import json
import os
from datetime import datetime, timezone

MODEL_DIR = Path(os.getenv("MODEL_DIR", "../models")).resolve()
DB_FILE = MODEL_DIR / "registry.db"
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

def init_registry():
    conn = sqlite3.connect(str(DB_FILE))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            symbol TEXT,
            model_path TEXT,
            booster_path TEXT,
            features TEXT,
            metrics TEXT,
            params TEXT,
            created_at TEXT
        );
    """)
    conn.commit()
    conn.close()

def register_model(name, symbol, model_path, booster_path=None, features=None, metrics=None, params=None):
    init_registry()
    conn = sqlite3.connect(str(DB_FILE))
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO models (name, symbol, model_path, booster_path, features, metrics, params, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name, symbol, str(model_path), str(booster_path) if booster_path else None,
        json.dumps(features or []), json.dumps(metrics or {}), json.dumps(params or {}), datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()
    conn.close()

def list_models(limit=20):
    init_registry()
    conn = sqlite3.connect(str(DB_FILE))
    cur = conn.cursor()
    cur.execute("SELECT id, name, symbol, model_path, booster_path, features, metrics, params, created_at FROM models ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "name": r[1], "symbol": r[2], "model_path": r[3], "booster_path": r[4],
            "features": json.loads(r[5] or "[]"), "metrics": json.loads(r[6] or "{}"),
            "params": json.loads(r[7] or "{}"), "created_at": r[8]
        })
    return out
