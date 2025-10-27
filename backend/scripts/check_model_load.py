# check_model_load.py
import os, json, joblib, lightgbm as lgb
MODEL_DIR = os.environ.get("MODEL_DIR", "E:\\predictior\\models")
latest = os.path.join(MODEL_DIR, "latest.json")
print("Using MODEL_DIR:", MODEL_DIR)
print("latest.json path:", latest)
print("exists:", os.path.exists(latest))
with open(latest) as f:
    info = json.load(f)
print("latest.json:", info)
booster = os.path.join(MODEL_DIR, info.get("booster_file",""))
joblib_path = os.path.join(MODEL_DIR, info.get("model_file",""))
print("booster exists:", os.path.exists(booster), booster)
print("joblib exists:", os.path.exists(joblib_path), joblib_path)

try:
    b = lgb.Booster(model_file=str(booster))
    print("Loaded booster OK")
except Exception as e:
    print("Booster load error:", e)

try:
    m = joblib.load(str(joblib_path))
    print("Loaded joblib OK (type:)", type(m))
except Exception as e:
    print("joblib load error:", e)
