// frontend/lib/api.ts
const BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

export interface Symbol {
  symbol: string;
  timeframe: string | null;
  file: string;
  path: string;
  category?: string;
}

export interface OHLCVDataPoint {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OHLCVResponse {
  symbol: string;
  timeframe: string;
  rows: number;
  data: OHLCVDataPoint[];
}

export interface Prediction {
  model_version: string;
  pred_next_1h_return: number;
  pred_prob_up: number;
  ts: string;
}

export interface BacktestResponse {
  file: string;
}

export interface User {
  email: string;
  quota_remaining: number;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

const getAuthHeaders = () => {
  if (typeof window === 'undefined') return { 'Content-Type': 'application/json' };
  const token = localStorage.getItem('token');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
};

const handleResponse = async (res: Response) => {
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const json = await res.json();
      msg = json.detail ?? json.message ?? JSON.stringify(json);
    } catch {}
    throw new ApiError(res.status, msg);
  }
  // try to parse json, otherwise return null
  const text = await res.text();
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return text;
  }
};

export const fetchSymbols = async (): Promise<Symbol[]> => {
  const res = await fetch(`${BASE}/market/symbols`, { headers: getAuthHeaders() });
  return handleResponse(res);
};

export const fetchOHLCV = async (symbol: string, timeframe: string, rows = 300): Promise<OHLCVResponse> => {
  const params = new URLSearchParams({ symbol, timeframe, rows: String(rows) });
  const res = await fetch(`${BASE}/market/ohlcv?${params}`, { headers: getAuthHeaders() });
  return handleResponse(res);
};

export const fetchPrediction = async (symbol: string, timeframe: string): Promise<Prediction> => {
  const params = new URLSearchParams({ symbol, timeframe });
  const res = await fetch(`${BASE}/predict?${params}`, { headers: getAuthHeaders() });
  return handleResponse(res);
};

export async function fetchBacktestLatest(symbol?: string): Promise<BacktestResponse> {
  const q = symbol ? `?symbol=${encodeURIComponent(symbol)}` : '';
  const res = await fetch(`${BASE}/market/backtest/latest${q}`, { method: 'GET', headers: getAuthHeaders() });
  if (!res.ok) {
    // bubble up ApiError for the caller to inspect status
    const text = await res.text();
    throw new ApiError(res.status, text || res.statusText);
  }
  return (await res.json()) as BacktestResponse;
}

export function getBacktestImageUrl(filename: string) {
  return `${BASE}/market/backtest/raw?file=${encodeURIComponent(filename)}`;
}

// simple auth wrapper to store token locally (keeps previous behaviour)

export const auth = {
  async login(email: string, password: string) {
    const res = await fetch(`${BASE}/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await handleResponse(res);
    if (typeof window !== 'undefined') {
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user_email', email);
    }
    return data;
  },

  logout() {
    if (typeof window === 'undefined') return;
    localStorage.removeItem('token');
    localStorage.removeItem('user_email');
    localStorage.removeItem('token_expires_at');
  },

  getUser(): User | null {
    if (typeof window === 'undefined') return null;
    const email = localStorage.getItem('user_email');
    if (!email) return null;
    return { email, quota_remaining: 100 };
  },

  isAuthenticated(): boolean {
    if (typeof window === 'undefined') return false;
    // simple check: token presence implies authenticated; keep this simple
    const token = localStorage.getItem('token');
    return !!token;
  },
};
