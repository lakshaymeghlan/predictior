// app/predictor/page.tsx
'use client';

import { useEffect, useMemo, useState } from 'react';
import { Copy, RefreshCw, Clock, TrendingUp, CheckCircle } from 'lucide-react';
import AuthGuard from '@/app/components/AuthGuard';
import Navbar from '@/app/components/Navbar';
import Loader from '@/app/components/Loader';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { Toaster } from '@/components/ui/sonner';
import {
  fetchSymbols,
  fetchOHLCV,
  fetchPrediction,
  fetchBacktestLatest,
  getBacktestImageUrl,
  Prediction,
  OHLCVResponse,
} from '@/lib/api';
import { Line } from 'react-chartjs-2';
import Chart from 'chart.js/auto';

export default function Predictor() {
  return (
    <AuthGuard>
      <PredictorContent />
      <Toaster position="top-right" theme="dark" />
    </AuthGuard>
  );
}

function PredictorContent() {
  const [symbols, setSymbols] = useState<{ symbol: string; label: string }[]>([]);
  const [symbol, setSymbol] = useState('BTC/USDT');
  const [timeframe, setTimeframe] = useState('1h');

  const [ohlcv, setOhlcv] = useState<OHLCVResponse | null>(null);
  const [loadingOhlcv, setLoadingOhlcv] = useState(false);

  const [loadingPrediction, setLoadingPrediction] = useState(false);
  const [currentPrediction, setCurrentPrediction] = useState<Prediction | null>(null);
  const [history, setHistory] = useState<Prediction[]>([]);

  const [backtestUrl, setBacktestUrl] = useState<string | null>(null);
  const [loadingBacktest, setLoadingBacktest] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetchSymbols();
        const normalized = res
          .map((s: any) => {
            if (typeof s === 'string') return { symbol: s, label: s };
            const sym = s.symbol ?? s.file ?? JSON.stringify(s);
            const label = s.label ?? s.symbol ?? s.file ?? s.path ?? String(sym);
            return { symbol: String(sym), label: String(label) };
          })
          .filter(Boolean);
        const fallback = [{ symbol: 'BTC/USDT', label: 'BTC/USDT — default' }];
        setSymbols(normalized.length ? normalized : fallback);
        const hasBTC = normalized.find((x) => x.symbol === 'BTC/USDT');
        const defaultSym = hasBTC ? 'BTC/USDT' : normalized[0]?.symbol ?? 'BTC/USDT';
        setSymbol((prev) => (prev && normalized.find((s) => s.symbol === prev) ? prev : defaultSym));
      } catch (err: any) {
        console.error('fetchSymbols error', err);
        toast.error('Failed to load symbols, using defaults');
        const defs = [
          { symbol: 'BTC/USDT', label: 'BTC/USDT — default' },
          { symbol: 'ETH/USDT', label: 'ETH/USDT — default' },
          { symbol: 'AAPL', label: 'AAPL — default' },
        ];
        setSymbols(defs);
        setSymbol('BTC/USDT');
      }
    })();
  }, []);

  async function ensureBacktest(symbolToCheck: string): Promise<string | null> {
    try {
      const resp = await fetchBacktestLatest(symbolToCheck);
      return resp?.file ?? null;
    } catch (err: any) {
      if (err?.status === 404) return null;
      console.warn('ensureBacktest error', err);
      return null;
    }
  }

  const fetchOhlcvFor = async (sym = symbol, tf = timeframe) => {
    setLoadingOhlcv(true);
    try {
      const data = await fetchOHLCV(sym, tf);
      setOhlcv(data);
    } catch (err: any) {
      console.error('fetchOHLCV error', err);
      toast.error('Failed to load OHLCV data');
      setOhlcv(null);
    } finally {
      setLoadingOhlcv(false);
    }
  };

  const fetchPredictionFor = async (sym = symbol, tf = timeframe) => {
    setLoadingPrediction(true);
    try {
      const pred = await fetchPrediction(sym, tf);
      setCurrentPrediction(pred);
      setHistory((prev) => [pred, ...prev].slice(0, 50));
    } catch (err: any) {
      console.error('fetchPrediction error', err);
      toast.error('Prediction failed');
      setCurrentPrediction(null);
    } finally {
      setLoadingPrediction(false);
    }
  };

  const fetchBacktest = async (sym = symbol) => {
    setLoadingBacktest(true);
    try {
      const filename = await ensureBacktest(sym);
      if (filename) {
        // use getBacktestImageUrl helper to build full URL
        const url = getBacktestImageUrl(filename);
        setBacktestUrl(url);
      } else {
        setBacktestUrl(null);
      }
    } catch (err) {
      console.error('fetchBacktest error', err);
      setBacktestUrl(null);
    } finally {
      setLoadingBacktest(false);
    }
  };

  // initial load & poll
  useEffect(() => {
    fetchOhlcvFor();
    fetchPredictionFor();
    fetchBacktest();
    const t = setInterval(() => {
      fetchPredictionFor();
    }, 30000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchOhlcvFor();
    fetchPredictionFor();
    fetchBacktest();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, timeframe]);

  useEffect(() => {
    return () => {
      if (backtestUrl) {
        try {
          URL.revokeObjectURL(backtestUrl);
        } catch {}
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const labels = useMemo(() => {
    if (!ohlcv?.data) return [];
    return ohlcv.data.map((r) => {
      try {
        return new Date(r.timestamp).toLocaleString();
      } catch {
        return String(r.timestamp);
      }
    });
  }, [ohlcv]);

  const closes = useMemo(() => {
    if (!ohlcv?.data) return [];
    return ohlcv.data.map((r) => Number((r as any).close ?? 0));
  }, [ohlcv]);

  const chartData = useMemo(
    () => ({
      labels,
      datasets: [
        {
          label: `${symbol} close`,
          data: closes,
          fill: false,
          tension: 0.1,
        },
      ],
    }),
    [labels, closes, symbol]
  );

  const lastClose = useMemo(() => {
    if (!ohlcv?.data || ohlcv.data.length === 0) return null;
    return Number(ohlcv.data[ohlcv.data.length - 1].close ?? 0);
  }, [ohlcv]);

  const prevClose = useMemo(() => {
    if (!ohlcv?.data || ohlcv.data.length < 2) return null;
    return Number(ohlcv.data[ohlcv.data.length - 2].close ?? 0);
  }, [ohlcv]);

  const priceDelta = useMemo(() => {
    if (lastClose == null || prevClose == null) return null;
    const diff = lastClose - prevClose;
    return {
      diff,
      pct: prevClose ? (diff / prevClose) * 100 : 0,
      up: diff > 0,
    };
  }, [lastClose, prevClose]);

  const handleCopyModel = () => {
    if (currentPrediction?.model_version) {
      navigator.clipboard.writeText(currentPrediction.model_version);
      toast.success('Model version copied to clipboard!');
    }
  };

  return (
    <div className="min-h-screen bg-[var(--dark-navy)]">
      <Navbar />

      <main className="container mx-auto px-4 py-8">
        <div className="mb-8 animate-fade-in">
          <h1 className="text-4xl font-bold neon-text mb-2">Prediction Generator</h1>
          <p className="text-[var(--text-secondary)]">Request predictions for any symbol and timeframe</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <div className="glass-card p-6 animate-slide-up">
              <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-6">Request Prediction</h2>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                <div>
                  <label className="text-sm text-[var(--text-muted)] mb-2 block">Symbol</label>
                  <select
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value)}
                    className="w-full p-2 rounded bg-[var(--card-bg)] border border-[var(--border-subtle)] text-[var(--text-primary)]"
                  >
                    {symbols.map((s) => (
                      <option key={s.symbol} value={s.symbol}>
                        {s.label ?? s.symbol}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="text-sm text-[var(--text-muted)] mb-2 block">Timeframe</label>
                  <select
                    value={timeframe}
                    onChange={(e) => setTimeframe(e.target.value)}
                    className="w-full p-2 rounded bg-[var(--card-bg)] border border-[var(--border-subtle)] text-[var(--text-primary)]"
                  >
                    <option value="1h">1h</option>
                    <option value="4h">4h</option>
                    <option value="1d">1d</option>
                  </select>
                </div>
              </div>

              <div className="flex gap-3">
                <Button
                  onClick={() => fetchPredictionFor()}
                  disabled={loadingPrediction}
                  className="flex-1 bg-[var(--neon-cyan)] text-[var(--dark-navy)] hover:shadow-lg hover:shadow-[var(--neon-cyan-glow)] font-semibold"
                >
                  {loadingPrediction ? (
                    <>
                      <Loader size="sm" />
                      <span className="ml-2">Generating...</span>
                    </>
                  ) : (
                    <>
                      <TrendingUp className="h-5 w-5 mr-2" />
                      Generate Prediction
                    </>
                  )}
                </Button>

                <Button
                  onClick={() => {
                    fetchOhlcvFor();
                    fetchPredictionFor();
                    fetchBacktest();
                    toast.success('Refreshed');
                  }}
                  variant="ghost"
                  className="flex-none"
                >
                  <RefreshCw className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {currentPrediction && (
              <div className="glass-card p-6 animate-slide-up neon-glow">
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-xl font-semibold text-[var(--text-primary)]">Latest Prediction</h2>
                  <CheckCircle className="h-6 w-6 text-[var(--success-green)]" />
                </div>

                <div className="space-y-4">
                  <div className="flex items-center justify-between p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-subtle)]">
                    <div>
                      <p className="text-sm text-[var(--text-muted)] mb-1">Model Version</p>
                      <p className="text-lg font-mono text-[var(--text-primary)]">{currentPrediction.model_version}</p>
                      <div className="text-sm text-[var(--text-muted)] mt-1">
                        Last: {lastClose ? lastClose.toFixed(2) : '—'}{' '}
                        {priceDelta && (
                          <span className={`ml-2 ${priceDelta.up ? 'text-[var(--success-green)]' : 'text-[var(--error-red)]'}`}>
                            {priceDelta.up ? '▲' : '▼'} {priceDelta.diff.toFixed(2)} ({priceDelta.pct.toFixed(2)}%)
                          </span>
                        )}
                      </div>
                    </div>
                    <Button onClick={handleCopyModel} variant="ghost" size="sm" className="text-[var(--neon-cyan)]">
                      <Copy className="h-4 w-4" />
                    </Button>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-subtle)]">
                      <p className="text-sm text-[var(--text-muted)] mb-2">1h Return</p>
                      <p
                        className={`text-3xl font-bold ${
                          currentPrediction.pred_next_1h_return > 0 ? 'text-[var(--success-green)]' : 'text-[var(--error-red)]'
                        }`}
                      >
                        {(currentPrediction.pred_next_1h_return * 100).toFixed(2)}%
                      </p>
                    </div>

                    <div className="p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-subtle)]">
                      <p className="text-sm text-[var(--text-muted)] mb-2">P(Up)</p>
                      <p className="text-3xl font-bold text-[var(--neon-cyan)]">{(currentPrediction.pred_prob_up * 100).toFixed(1)}%</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
                    <Clock className="h-4 w-4" />
                    {new Date(currentPrediction.ts).toLocaleString()}
                  </div>
                </div>
              </div>
            )}

            <div className="bg-[var(--card-bg)] p-6 rounded shadow">
              <strong className="block mb-3">Price chart</strong>
              {loadingOhlcv ? (
                <div className="py-8 text-center">
                  <Loader />
                  <div className="text-[var(--text-muted)] mt-2">Loading OHLCV…</div>
                </div>
              ) : ohlcv && ohlcv.data && ohlcv.data.length ? (
                <div style={{ height: 360 }}>
                  <Line data={chartData} />
                </div>
              ) : (
                <div className="py-8 text-center text-[var(--text-muted)]">No OHLCV data</div>
              )}
            </div>
          </div>

          <div className="space-y-6">
            <div className="glass-card p-6 animate-slide-up" style={{ animationDelay: '0.1s' }}>
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-semibold text-[var(--text-primary)]">History</h2>
                {history.length > 0 && (
                  <Button onClick={() => setHistory([])} variant="ghost" size="sm" className="text-[var(--text-muted)]">
                    Clear
                  </Button>
                )}
              </div>

              {history.length === 0 ? (
                <div className="text-center py-8">
                  <RefreshCw className="h-12 w-12 text-[var(--text-muted)] mx-auto mb-3" />
                  <p className="text-[var(--text-secondary)]">No predictions yet</p>
                  <p className="text-sm text-[var(--text-muted)] mt-2">Generate your first prediction to see history</p>
                </div>
              ) : (
                <div className="space-y-3 max-h-[600px] overflow-y-auto">
                  {history.map((pred, index) => (
                    <div key={index} className="p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-subtle)] hover:border-[var(--border-medium)] transition-all">
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-xs font-mono text-[var(--text-muted)]">{pred.model_version.slice(0, 12)}...</p>
                        <p className="text-xs text-[var(--text-muted)]">{new Date(pred.ts).toLocaleTimeString()}</p>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className={`text-sm font-semibold ${pred.pred_next_1h_return > 0 ? 'text-[var(--success-green)]' : 'text-[var(--error-red)]'}`}>
                          {(pred.pred_next_1h_return * 100).toFixed(2)}%
                        </span>
                        <span className="text-sm text-[var(--neon-cyan)]">P: {(pred.pred_prob_up * 100).toFixed(1)}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="glass-card p-6 animate-slide-up" style={{ animationDelay: '0.15s' }}>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-xl font-semibold text-[var(--text-primary)]">Equity plot</h2>
                <Button
                  onClick={() => {
                    fetchBacktest();
                    toast.success('Refreshing backtest…');
                  }}
                  variant="ghost"
                  size="sm"
                  className="text-[var(--text-muted)]"
                >
                  Refresh
                </Button>
              </div>

              {loadingBacktest ? (
                <div className="py-8 text-center">
                  <Loader />
                  <div className="text-[var(--text-muted)] mt-2">Loading backtest…</div>
                </div>
              ) : backtestUrl ? (
                <img src={backtestUrl} alt="Backtest equity" style={{ width: '100%', maxHeight: 400, objectFit: 'contain' }} />
              ) : (
                <div className="py-8 text-center text-[var(--text-muted)]">No backtest image available</div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
