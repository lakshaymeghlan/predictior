const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function defaultHeaders(token) {
  const h = { "Content-Type": "application/json" };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

export async function register({ email, password }) {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: defaultHeaders(),
    body: JSON.stringify({ email, password })
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || "Registration failed");
  }
  return res.json();
}

export async function login({ email, password }) {
  const res = await fetch(`${API_BASE}/auth/token`, {
    method: "POST",
    headers: defaultHeaders(),
    body: JSON.stringify({ email, password })
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || "Login failed");
  }
  const data = await res.json();
  // save token locally
  if (data.access_token) localStorage.setItem("PRED_TOKEN", data.access_token);
  return data;
}

export function logout() {
  localStorage.removeItem("PRED_TOKEN");
}

export async function getCurrentUser(token) {
  const t = token || localStorage.getItem("PRED_TOKEN");
  if (!t) throw new Error("Not authenticated");
  const res = await fetch(`${API_BASE}/dashboard/me`, { headers: defaultHeaders(t) });
  if (!res.ok) throw new Error("Not authenticated");
  return res.json();
}

export async function predict(symbol = "BTC/USDT", timeframe = "1h", use_ensemble = false) {
  const token = localStorage.getItem("PRED_TOKEN");
  const url = new URL(`${API_BASE}/predict`);
  url.searchParams.set("symbol", symbol);
  url.searchParams.set("timeframe", timeframe);
  if (use_ensemble) url.searchParams.set("use_ensemble", "true");
  const res = await fetch(url.toString(), { headers: defaultHeaders(token) });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Prediction failed");
  }
  return res.json();
}

export async function fetchBacktestLatest() {
  const token = localStorage.getItem("PRED_TOKEN");
  const res = await fetch(`${API_BASE}/backtest/latest`, { headers: defaultHeaders(token) });
  if (!res.ok) {
    throw new Error("No backtest available");
  }
  const contentType = res.headers.get("content-type");
  const blob = await res.blob();
  return { blob, contentType };
}
