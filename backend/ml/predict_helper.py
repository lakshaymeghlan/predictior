import joblib
import json
import pandas as pd
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent / "../models"
MODEL_DIR = MODEL_DIR.resolve()

def load_latest_model():
    latest = MODEL_DIR / "latest.json"
    if not latest.exists():
        raise FileNotFoundError("latest.json not found in models dir. Run training first.")
    with open(latest, "r") as f:
        info = json.load(f)
    model = joblib.load(info["model_file"])
    features = info["features"]
    return model, features

def predict_from_features(df_features: pd.DataFrame):
    model, features = load_latest_model()
    X = df_features[features]
    preds = model.predict(X)
    out = pd.Series(preds, index=X.index, name="pred_next_1h_return")
    return out

if __name__ == "__main__":
    print("Run this after training — example usage from your feature pipeline.")
