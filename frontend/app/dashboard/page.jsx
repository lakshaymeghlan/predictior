"use client";

import { useEffect, useState } from "react";
import { Line, Candlestick } from "react-chartjs-2"; // Candlestick needs extra plugin — we'll use Line for equity and OHLC close line
import Chart from "chart.js/auto";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function DashboardPage() {
  const [symbols, setSymbols] = useState([]);
  const [selected, setSelected] = useState("BTC/USDT");
  const [pred, setPred] = useState(null);
  const [equityImg, setEquityImg] = useState(null);
  const [ohlcv, setOhlcv] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchSymbols();
  }, []);

  useEffect(() => {
    if (selected) {
      fetchPrediction();
      fetchOhlcv();
      fetchBacktest();
    }
    // eslint-disable-next-line
  }, [selected]);

  async function fetchSymbols() {
    try {
      const r = await fetch(`${API}/market/symbols`);
      const j = await r.json();
      setSymbols(j.symbols || []);
      if (j.symbols && j.symbols[0]) setSelected(j.symbols[0].symbol);
    } catch (e) {
      console.error(e);
    }
  }

  async function fetchPrediction() {
    setLoading(true);
    try {
      const r = await fetch(`${API}/predict?symbol=${encodeURIComponent(selected)}&timeframe=1h`);
      const j = await r.json();
      setPred(j);
    } catch (e) {
      setPred({ error: "Unable to fetch prediction" });
    } finally {
      setLoading(false);
    }
  }

  async function fetchOhlcv() {
    try {
      const r = await fetch(`${API}/market/ohlcv?symbol=${encodeURIComponent(selected)}&timeframe=1h&rows=300`);
      const j = await r.json();
      setOhlcv(j.data || []);
    } catch (e) {
      setOhlcv([]);
    }
  }

  async function fetchBacktest() {
    try {
      const r = await fetch(`${API}/market/backtest/latest?symbol=${encodeURIComponent(selected)}`);
      if (!r.ok) {
        setEquityImg(null);
        return;
      }
      const blob = await r.blob();
      setEquityImg(URL.createObjectURL(blob));
    } catch (e) {
      setEquityImg(null);
    }
  }

  // prepare dataset for Chart.js (OHLC close price)
  const lineData = {
    labels: ohlcv.map((r) => new Date(r.ts).toLocaleString()),
    datasets: [
      {
        label: `${selected} close`,
        data: ohlcv.map((r) => r.close),
        tension: 0.1,
        pointRadius: 0,
      },
    ],
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-8">
      <div className="max-w-5xl mx-auto">
        <header className="flex items-center justify-between mb-6">
          <div className="text-3xl font-bold">Dashboard</div>
          <div className="flex items-center gap-4">
            <select value={selected} onChange={(e)=>setSelected(e.target.value)} className="bg-slate-800 px-3 py-2 rounded">
              {symbols.map(s=> <option key={s.symbol} value={s.symbol}>{s.symbol} — {s.type}</option>)}
            </select>
          </div>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="md:col-span-2 bg-slate-800 p-6 rounded-2xl shadow">
            <div className="text-lg font-semibold mb-3">Latest prediction</div>
            {loading ? <div>Loading…</div> : pred ? (
              pred.error ? <div className="text-red-400">{pred.error}</div> : (
                <>
                  <div className="text-sm text-slate-400 mb-1">{pred.model_version}</div>
                  <div className="text-2xl font-bold">{Number.isFinite(pred.pred_next_1h_return) ? `${(pred.pred_next_1h_return*100).toFixed(3)}%` : "—"}</div>
                  <div className="text-sm text-emerald-400 mt-1">{Number.isFinite(pred.pred_prob_up) ? `P(up): ${(pred.pred_prob_up*100).toFixed(1)}%` : "P(up): —"}</div>
                </>
              )
            ) : <div>No prediction</div>}
            <div className="mt-4">
              <button onClick={fetchPrediction} className="px-4 py-2 bg-rose-600 rounded">Refresh</button>
            </div>
            <div className="mt-6">
              <div className="text-lg font-semibold mb-2">Price (last {ohlcv.length} points)</div>
              {ohlcv.length ? <Line data={lineData} /> : <div className="text-slate-400">No OHLCV data</div>}
            </div>
          </div>

          <div className="bg-slate-800 p-6 rounded-2xl shadow">
            <div className="text-lg font-semibold mb-3">Account</div>
            <div className="text-sm">Email: (from auth)</div>
            <div className="text-sm mt-2">Quota remaining: <strong>TODO</strong></div>
            <div className="mt-6">
              <div className="text-lg font-semibold">Equity plot</div>
              {equityImg ? <img src={equityImg} alt="equity" className="mt-3 w-full rounded"/> : <div className="text-slate-400 mt-2">No backtest image available</div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
