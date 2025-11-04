// app/dashboard/page.tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import {
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Download,
  Search,
  AlertCircle,
  Info,
  Clock,
  Activity,
} from "lucide-react";
import AuthGuard from "@/app/components/AuthGuard";
import Navbar from "@/app/components/Navbar";
import Loader, { CardSkeleton } from "@/app/components/Loader";
import {
  fetchSymbols,
  fetchOHLCV,
  fetchPrediction,
  fetchBacktestLatest,
  getBacktestImageUrl,
  Symbol as ApiSymbol,
  OHLCVResponse,
  Prediction,
  ApiError,
  auth,
} from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Toaster } from "@/components/ui/sonner";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip as ChartTooltip,
  LineChart,
  Line,
} from "recharts";

const API_BASE = (
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

export default function Dashboard() {
  return (
    <AuthGuard>
      <DashboardContent />
      <Toaster position="top-right" theme="dark" />
    </AuthGuard>
  );
}

function DashboardContent() {
  const [symbols, setSymbols] = useState<ApiSymbol[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>(""); // format: "<symbol>_<timeframe>"
  const [searchQuery, setSearchQuery] = useState("");
  const [ohlcvData, setOhlcvData] = useState<OHLCVResponse | null>(null);
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [backtestFile, setBacktestFile] = useState<string | null>(null);
  const [loading, setLoading] = useState({
    symbols: true,
    ohlcv: false,
    prediction: false,
    backtest: false,
  });

  const [user, setUser] = useState(() => auth.getUser());
  const [marketSnapshot, setMarketSnapshot] = useState<any[]>([]);
  const [snapshotLoading, setSnapshotLoading] = useState(false);

  useEffect(() => {
    // load user once (in case token is present)
    setUser(auth.getUser());
  }, []);

  useEffect(() => {
    loadSymbols();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // load market snapshot on mount and every 60s
  useEffect(() => {
    let mounted = true;
    const loadSnapshot = async () => {
      setSnapshotLoading(true);
      try {
        const res = await fetch(`${API_BASE}/market/live_summary`);
        const j = await res.json();
        if (!mounted) return;
        setMarketSnapshot(j?.data ?? []);
      } catch (e) {
        console.warn("market snapshot fetch failed", e);
        if (mounted) setMarketSnapshot([]);
      } finally {
        if (mounted) setSnapshotLoading(false);
      }
    };
    loadSnapshot();
    const t = setInterval(loadSnapshot, 60_000);
    return () => {
      mounted = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (selectedSymbol) {
      loadData(selectedSymbol);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSymbol]);

  const loadSymbols = async () => {
    setLoading((s) => ({ ...s, symbols: true }));
    try {
      const data = await fetchSymbols();
      const normalized = (data ?? []).map((s: any) => ({
        symbol: s.symbol,
        timeframe: s.timeframe ?? "1h",
        file: s.file ?? "",
        path: s.path ?? "",
        category:
          s.category ??
          (s.symbol?.includes("USDT")
            ? "crypto"
            : s.symbol?.includes("GLD")
            ? "commodity"
            : "stock"),
      }));

      setSymbols(normalized);

      // choose default, prefer BTC but fall back to first
      if (normalized.length > 0) {
        const btc = normalized.find(
          (x: { symbol: string }) =>
            x.symbol === "BTC/USDT" || x.symbol.startsWith("BTC")
        );
        const pick = btc ?? normalized[0];
        setSelectedSymbol(`${pick.symbol}_${pick.timeframe}`);
      }
    } catch (err) {
      handleError(err, "Failed to load symbols");
      // fallback defaults
      const fallback = [
        {
          symbol: "BTC/USDT",
          timeframe: "1h",
          file: "",
          path: "",
          category: "crypto",
        },
        {
          symbol: "ETH/USDT",
          timeframe: "1h",
          file: "",
          path: "",
          category: "crypto",
        },
        {
          symbol: "AAPL",
          timeframe: "1d",
          file: "",
          path: "",
          category: "stock",
        },
      ];
      setSymbols(fallback);
      setSelectedSymbol(`${fallback[0].symbol}_${fallback[0].timeframe}`);
    } finally {
      setLoading((s) => ({ ...s, symbols: false }));
    }
  };

  async function ensureBacktest(symbolToCheck: string): Promise<string | null> {
    try {
      const resp = await fetchBacktestLatest(symbolToCheck);
      return resp?.file ?? null;
    } catch (err: any) {
      if (err?.status === 404) return null;
      console.warn("ensureBacktest error", err);
      return null;
    }
  }

  const loadData = async (symbolKey: string) => {
    const [symbol, timeframe] = symbolKey.split("_");
    setLoading((s) => ({
      ...s,
      ohlcv: true,
      prediction: true,
      backtest: true,
    }));

    try {
      const [ohlcv, pred] = await Promise.all([
        fetchOHLCV(symbol, timeframe, 300),
        fetchPrediction(symbol, timeframe),
      ]);
      setOhlcvData(ohlcv);
      setPrediction(pred);
    } catch (err) {
      handleError(err, "Failed to load market data");
      setOhlcvData(null);
      setPrediction(null);
    } finally {
      setLoading((s) => ({ ...s, ohlcv: false, prediction: false }));
    }

    // Backtest: ensure symbol-specific backtest exists (or schedule & poll), then set filename
    try {
      const filename = await ensureBacktest(symbol);
      if (filename) {
        setBacktestFile(filename);
      } else {
        setBacktestFile(null);
      }
    } catch (e) {
      console.error("Backtest ensure error", e);
      setBacktestFile(null);
    } finally {
      setLoading((s) => ({ ...s, backtest: false }));
    }
  };

  // auto-refresh OHLCV & prediction every 60s for currently selected symbol
  useEffect(() => {
    if (!selectedSymbol) return;
    const t = setInterval(() => {
      loadData(selectedSymbol);
    }, 60_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSymbol]);

  const handleRefresh = () => {
    if (!selectedSymbol) return;
    toast.info("Refreshing data...");
    loadData(selectedSymbol);
  };

  const handleError = (error: unknown, defaultMessage: string) => {
    if (error instanceof ApiError) {
      toast.error(error.message);
    } else {
      console.error(error);
      toast.error(defaultMessage);
    }
  };

  const inferCategory = (symbol: string) => {
    if (!symbol) return "unknown";
    if (
      symbol.includes("BTC") ||
      symbol.includes("ETH") ||
      symbol.includes("USDT")
    )
      return "crypto";
    if (symbol.includes("GLD") || symbol.includes("OIL")) return "commodity";
    return "stock";
  };

  const filteredSymbols = symbols.filter((s) =>
    `${s.symbol} ${s.timeframe} ${s.category}`
      .toLowerCase()
      .includes(searchQuery.toLowerCase())
  );

  // chart data for recharts
  const chartData = useMemo(
    () =>
      ohlcvData?.data.map((d) => ({
        timestamp: new Date(d.timestamp).toLocaleString(),
        close: d.close,
        volume: d.volume,
      })) ?? [],
    [ohlcvData]
  );

  // sparkline from prediction
  const sparklineData = useMemo(
    () =>
      prediction
        ? Array.from({ length: 10 }, (_, i) => ({
            value: prediction.pred_next_1h_return * (0.8 + Math.random() * 0.4),
          }))
        : [],
    [prediction]
  );

  // last close and delta
  const lastClose = useMemo(() => {
    if (!ohlcvData?.data || ohlcvData.data.length === 0) return null;
    return Number(ohlcvData.data[ohlcvData.data.length - 1].close ?? 0);
  }, [ohlcvData]);

  const prevClose = useMemo(() => {
    if (!ohlcvData?.data || ohlcvData.data.length < 2) return null;
    return Number(ohlcvData.data[ohlcvData.data.length - 2].close ?? 0);
  }, [ohlcvData]);

  const priceDelta = useMemo(() => {
    if (lastClose == null || prevClose == null) return null;
    const diff = lastClose - prevClose;
    return {
      diff,
      pct: prevClose ? (diff / prevClose) * 100 : 0,
      up: diff > 0,
    };
  }, [lastClose, prevClose]);

  return (
    <div className="min-h-screen bg-[var(--dark-navy)]">
      <Navbar />

      <main className="container mx-auto px-4 py-8">
        <div className="mb-6 animate-fade-in">
          <h1 className="text-4xl font-bold neon-text mb-2">Predictor AI</h1>
          <p className="text-[var(--text-secondary)] animate-pulse-soft">
            Real-time market predictions powered by AI
          </p>
        </div>

        {/* Market Snapshot (top row) */}
        <div className="mb-6">
          <div className="glass-card p-4 animate-slide-up">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-lg font-semibold text-[var(--text-primary)]">
                Market Snapshot
              </h3>
              <div className="text-sm text-[var(--text-muted)]">
                {snapshotLoading
                  ? "Updating…"
                  : `Updated ${new Date().toLocaleTimeString()}`}
              </div>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {marketSnapshot.length === 0 ? (
                <div className="col-span-full text-sm text-[var(--text-muted)]">
                  No snapshot available
                </div>
              ) : (
                marketSnapshot.map((s: any) => (
                  <div
                    key={s.symbol}
                    className={`p-3 rounded-xl border flex flex-col items-center justify-center ${
                      s.up
                        ? "border-[var(--success-green)]"
                        : "border-[var(--error-red)]"
                    }`}
                  >
                    <div className="text-sm font-semibold">{s.symbol}</div>
                    {s.error ? (
                      // show short error (first 80 chars) to help debug in UI
                      <div
                        className="text-xs text-[var(--text-muted)] mt-1"
                        title={String(s.error)}
                      >
                        {String(s.error).slice(0, 80)}
                        {String(s.error).length > 80 ? "…" : ""}
                      </div>
                    ) : (
                      <>
                        <div
                          className={`text-lg font-bold mt-1 ${
                            s.up
                              ? "text-[var(--success-green)]"
                              : "text-[var(--error-red)]"
                          }`}
                        >
                          {s.change_pct.toFixed(2)}%
                        </div>
                        <div className="text-xs text-[var(--text-muted)] mt-1">
                          {Number(s.last_close).toFixed(2)}
                        </div>
                      </>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {loading.symbols ? (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-6">
              <div className="glass-card p-6 animate-slide-up">
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-xl font-semibold text-[var(--text-primary)]">
                    Prediction Overview
                  </h2>
                  <Button
                    onClick={handleRefresh}
                    variant="ghost"
                    size="sm"
                    className="text-[var(--neon-cyan)] hover:bg-[var(--card-bg)]"
                    disabled={loading.prediction}
                  >
                    <RefreshCw
                      className={`h-4 w-4 ${
                        loading.prediction ? "animate-spin" : ""
                      }`}
                    />
                  </Button>
                </div>

                {loading.prediction ? (
                  <Loader text="Loading prediction..." />
                ) : prediction ? (
                  <div className="space-y-4">
                    <div className="flex items-start justify-between">
                      <div className="space-y-1">
                        <p className="text-sm text-[var(--text-muted)]">
                          Model Version
                        </p>
                        <p className="text-lg font-mono text-[var(--text-primary)]">
                          {prediction.model_version}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 text-[var(--text-muted)] text-sm">
                        <Clock className="h-4 w-4" />
                        {new Date(prediction.ts).toLocaleString()}
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div className="p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-subtle)]">
                        <p className="text-sm text-[var(--text-muted)] mb-1">
                          Predicted 1h Return
                        </p>
                        <div className="flex items-center gap-2">
                          <p
                            className={`text-2xl font-bold ${
                              prediction.pred_next_1h_return > 0
                                ? "text-[var(--success-green)]"
                                : "text-[var(--error-red)]"
                            }`}
                          >
                            {(prediction.pred_next_1h_return * 100).toFixed(2)}%
                          </p>
                          {prediction.pred_next_1h_return > 0 ? (
                            <TrendingUp className="h-5 w-5 text-[var(--success-green)]" />
                          ) : (
                            <TrendingDown className="h-5 w-5 text-[var(--error-red)]" />
                          )}
                        </div>
                        <div className="text-sm text-[var(--text-muted)] mt-2">
                          Last: {lastClose ? lastClose.toFixed(2) : "—"}{" "}
                          {priceDelta && (
                            <span
                              className={`${
                                priceDelta.up
                                  ? "text-[var(--success-green)]"
                                  : "text-[var(--error-red)]"
                              }`}
                            >
                              {priceDelta.up ? "▲" : "▼"}{" "}
                              {priceDelta.diff.toFixed(2)} (
                              {priceDelta.pct.toFixed(2)}%)
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-subtle)]">
                        <p className="text-sm text-[var(--text-muted)] mb-1">
                          P(Up) Probability
                        </p>
                        <div className="flex items-center gap-3">
                          <p className="text-2xl font-bold text-[var(--neon-cyan)]">
                            {(prediction.pred_prob_up * 100).toFixed(1)}%
                          </p>
                          <div className="flex-1">
                            <ResponsiveContainer width="100%" height={30}>
                              <LineChart data={sparklineData}>
                                <Line
                                  type="monotone"
                                  dataKey="value"
                                  stroke="var(--neon-cyan)"
                                  strokeWidth={2}
                                  dot={false}
                                />
                              </LineChart>
                            </ResponsiveContainer>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="p-6">
                    <AlertCircle className="h-10 w-10 text-[var(--text-muted)] mb-3" />
                    <p className="text-[var(--text-secondary)]">
                      No prediction available
                    </p>
                  </div>
                )}
              </div>

              <div
                className="glass-card p-6 animate-slide-up"
                style={{ animationDelay: "0.1s" }}
              >
                <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-6">
                  Price Chart
                </h2>

                {loading.ohlcv ? (
                  <Loader text="Loading chart data..." />
                ) : chartData.length > 0 ? (
                  <div className="h-[400px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={chartData}>
                        <defs>
                          <linearGradient
                            id="colorClose"
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="1"
                          >
                            <stop
                              offset="5%"
                              stopColor="var(--neon-cyan)"
                              stopOpacity={0.3}
                            />
                            <stop
                              offset="95%"
                              stopColor="var(--neon-cyan)"
                              stopOpacity={0}
                            />
                          </linearGradient>
                        </defs>
                        <XAxis
                          dataKey="timestamp"
                          stroke="var(--text-muted)"
                          tick={{ fill: "var(--text-muted)", fontSize: 12 }}
                        />
                        <YAxis
                          stroke="var(--text-muted)"
                          tick={{ fill: "var(--text-muted)", fontSize: 12 }}
                        />
                        <ChartTooltip
                          contentStyle={{
                            backgroundColor: "var(--card-bg)",
                            border: "1px solid var(--border-subtle)",
                            borderRadius: 8,
                            color: "var(--text-primary)",
                          }}
                        />
                        <Area
                          type="monotone"
                          dataKey="close"
                          stroke="var(--neon-cyan)"
                          strokeWidth={2}
                          fill="url(#colorClose)"
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div className="p-6">
                    <p className="text-[var(--text-secondary)]">
                      No OHLCV data for {selectedSymbol}
                    </p>
                    <p className="text-sm text-[var(--text-muted)]">
                      Place CSV file in data folder or use live fallback
                    </p>
                  </div>
                )}
              </div>

              <div
                className="glass-card p-6 animate-slide-up"
                style={{ animationDelay: "0.2s" }}
              >
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-xl font-semibold text-[var(--text-primary)]">
                    Equity Plot
                  </h2>
                  {backtestFile && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-[var(--neon-cyan)] hover:bg-[var(--card-bg)]"
                      onClick={() => {
                        const link = document.createElement("a");
                        link.href = getBacktestImageUrl(backtestFile);
                        link.download = backtestFile;
                        link.click();
                      }}
                    >
                      <Download className="h-4 w-4 mr-2" />
                      Download
                    </Button>
                  )}
                </div>

                {loading.backtest ? (
                  <Loader text="Loading backtest..." />
                ) : backtestFile ? (
                  <img
                    src={getBacktestImageUrl(backtestFile)}
                    alt="Backtest equity plot"
                    className="w-full rounded-lg"
                  />
                ) : (
                  <div className="text-center py-8">
                    <Activity className="h-12 w-12 text-[var(--text-muted)] mx-auto mb-3" />
                    <p className="text-[var(--text-secondary)] mb-4">
                      No backtest data available yet
                    </p>
                    <Button
                      variant="outline"
                      className="border-[var(--neon-cyan)] text-[var(--neon-cyan)] hover:bg-[var(--neon-cyan)] hover:text-[var(--dark-navy)]"
                      onClick={async () => {
                        setLoading((s) => ({ ...s, backtest: true }));
                        const [symbol] = selectedSymbol.split("_");
                        const file = await ensureBacktest(symbol);
                        if (file) {
                          setBacktestFile(file);
                          toast.success("Backtest ready");
                        } else {
                          toast.error(
                            "Backtest scheduling timed out or failed"
                          );
                        }
                        setLoading((s) => ({ ...s, backtest: false }));
                      }}
                    >
                      Run Backtest
                    </Button>
                  </div>
                )}
              </div>
            </div>

            <div className="space-y-6">
              <div
                className="glass-card p-6 animate-slide-up"
                style={{ animationDelay: "0.1s" }}
              >
                <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-4">
                  Settings
                </h2>

                <div className="space-y-4">
                  <div>
                    <label className="text-sm text-[var(--text-muted)] mb-2 block">
                      Symbol / Timeframe
                    </label>
                    <div className="relative mb-2">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--text-muted)]" />
                      <Input
                        type="text"
                        placeholder="Search symbols..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="pl-10 bg-[var(--card-bg)] border-[var(--border-subtle)] text-[var(--text-primary)]"
                      />
                    </div>

                    <Select
                      value={selectedSymbol}
                      onValueChange={(v) => setSelectedSymbol(v)}
                    >
                      <SelectTrigger className="bg-[var(--card-bg)] border-[var(--border-subtle)] text-[var(--text-primary)]">
                        <SelectValue placeholder="Select symbol" />
                      </SelectTrigger>
                      <SelectContent className="bg-[var(--card-bg)] border-[var(--border-subtle)]">
                        {filteredSymbols.map((s) => (
                          <SelectItem
                            key={`${s.symbol}_${s.timeframe}`}
                            value={`${s.symbol}_${s.timeframe}`}
                            className="text-[var(--text-primary)] focus:bg-[var(--card-hover)] focus:text-[var(--text-primary)]"
                          >
                            <div className="flex items-center justify-between w-full">
                              <span className="font-medium">
                                {s.symbol}/{s.timeframe}
                              </span>
                              <span className="text-xs text-[var(--text-muted)] ml-2">
                                {s.category}
                              </span>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>

              <div
                className="glass-card p-6 animate-slide-up"
                style={{ animationDelay: "0.2s" }}
              >
                <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-4">
                  Account
                </h2>

                <div className="space-y-4">
                  <div>
                    <p className="text-sm text-[var(--text-muted)] mb-1">
                      Email
                    </p>
                    <p className="text-[var(--text-primary)] font-medium">
                      {user?.email ?? "Guest"}
                    </p>
                  </div>

                  <div className="p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-subtle)]">
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-sm text-[var(--text-muted)]">
                        Quota Remaining
                      </p>
                      <button
                        className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                        title="Number of API calls remaining this month. Resets on the 1st."
                      >
                        <Info className="h-4 w-4" />
                      </button>
                    </div>
                    <p className="text-2xl font-bold text-[var(--neon-cyan)]">
                      {user?.quota_remaining ?? 100}
                    </p>
                    <div className="w-full bg-[var(--dark-charcoal)] rounded-full h-2 mt-3">
                      <div
                        className="bg-[var(--neon-cyan)] h-2 rounded-full transition-all"
                        style={{
                          width: `${Math.min(
                            user?.quota_remaining ?? 100,
                            100
                          )}%`,
                        }}
                      />
                    </div>
                  </div>

                  {(user?.quota_remaining ?? 100) < 20 && (
                    <Button className="w-full bg-[var(--neon-cyan)] text-[var(--dark-navy)] hover:shadow-lg hover:shadow-[var(--neon-cyan-glow)]">
                      Subscribe for More
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function EmptyState({
  message,
  description,
}: {
  message: string;
  description?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-12">
      <AlertCircle className="h-12 w-12 text-[var(--text-muted)] mb-3" />
      <p className="text-[var(--text-secondary)] text-center">{message}</p>
      {description && (
        <p className="text-sm text-[var(--text-muted)] text-center mt-2">
          {description}
        </p>
      )}
    </div>
  );
}
