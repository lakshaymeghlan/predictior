"use client";

import { useEffect, useState } from "react";
import { Line } from "react-chartjs-2";
import Chart from "chart.js/auto";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function PredictorPage() {
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [timeframe, setTimeframe] = useState("1h");
  const [ohlcv, setOhlcv] = useState([]);
  const [loading, setLoading] = useState(false);
  const [prediction, setPrediction] = useState(null);
  // symbols will be an array of objects: { symbol, label }
  const [symbols, setSymbols] = useState([]);

  // --- load symbols from backend, tolerant to many formats ---
  async function loadSymbols() {
    try {
      const res = await fetch(`${API}/market/symbols`);
      if (!res.ok) throw new Error(`symbols fetch failed: ${res.status}`);
      const j = await res.json();

      // try different keys / shapes
      let list = j?.symbols ?? j?.data ?? j?.symbol_list ?? j;
      // if backend returned an object with data_dir_candidates & symbols (our new format), handle that
      if (j && typeof j === "object" && Array.isArray(j.symbols)) {
        list = j.symbols;
      } else if (j && typeof j === "object" && Array.isArray(j.data)) {
        list = j.data;
      }

      // Normalize to array of {symbol,label}
      let normalized = [];
      if (Array.isArray(list) && list.length) {
        for (const item of list) {
          if (!item) continue;
          if (typeof item === "string") {
            normalized.push({ symbol: item, label: item });
          } else if (typeof item === "object") {
            // accept {symbol,label} or {file/path} entries produced by scanning
            const sym = item.symbol ?? item.symbol?.toString() ?? (item.file ? item.file.split("_").slice(0,2).join("/").replace(".csv","") : null);
            const label = item.label ?? (sym ? `${sym} — ${item.type ?? "unknown"}` : item.file ?? JSON.stringify(item));
            if (sym) normalized.push({ symbol: sym, label });
          }
        }
      }

      // fallback defaults
      if (normalized.length === 0) {
        const defs = ["BTC/USDT","ETH/USDT","GLD","AAPL"];
        normalized = defs.map(d => ({ symbol: d, label: `${d} — default` }));
      }

      setSymbols(normalized);

      // pick a sensible default symbol
      const hasBTC = normalized.find(x => x.symbol === "BTC/USDT");
      const defaultSym = hasBTC ? "BTC/USDT" : normalized[0].symbol;
      setSymbol(prev => prev && normalized.find(s => s.symbol === prev) ? prev : defaultSym);
    } catch (e) {
      console.error("loadSymbols error", e);
      const defs = ["BTC/USDT","ETH/USDT","GLD","AAPL"];
      const normalized = defs.map(d => ({ symbol: d, label: `${d} — default` }));
      setSymbols(normalized);
      setSymbol("BTC/USDT");
    }
  }

  async function fetchOhlcv(sym = symbol, tf = timeframe) {
    setLoading(true);
    try {
      const res = await fetch(`${API}/market/ohlcv?symbol=${encodeURIComponent(sym)}&timeframe=${encodeURIComponent(tf)}&rows=500`);
      if (!res.ok) {
        // try to read error body safely
        const err = await res.text().catch(() => res.statusText);
        console.error("ohlcv error", err);
        setOhlcv([]);
        setLoading(false);
        return;
      }
      const json = await res.json();
      setOhlcv(json.data || []);
    } catch (e) {
      console.error(e);
      setOhlcv([]);
    } finally {
      setLoading(false);
    }
  }

  async function fetchPrediction() {
    try {
      const res = await fetch(`${API}/predict?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`);
      if (!res.ok) {
        const body = await res.json().catch(()=>({message:res.statusText}));
        setPrediction({ error: body.detail || body.message || "predict failed" });
        return;
      }
      const j = await res.json();
      setPrediction(j);
    } catch (e) {
      setPrediction({ error: String(e) });
    }
  }

  useEffect(() => {
    loadSymbols();
    fetchOhlcv();
    fetchPrediction();
    const t = setInterval(fetchPrediction, 30000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // when symbol or timeframe change, reload data
    fetchOhlcv();
    fetchPrediction();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, timeframe]);

  const labels = ohlcv.map(r => {
    try { return new Date(r.timestamp).toLocaleString(); } catch { return String(r.timestamp); }
  });
  const closes = ohlcv.map(r => Number(r.close ?? r.close_price ?? r.c ?? 0));

  const data = {
    labels,
    datasets: [
      {
        label: `${symbol} close`,
        data: closes,
        fill: false,
        tension: 0.1,
      }
    ]
  };

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-3xl font-bold">Dashboard</h1>
          <div>
            <select
              value={symbol}
              onChange={e => {
                const v = e.target.value;
                if (!v || v.trim() === "—") return;
                setSymbol(v);
              }}
              className="mr-2 bg-gray-700 text-gray-100 p-2 rounded"
            >
              {symbols.map(s => (
                <option key={s.symbol} value={s.symbol}>
                  {s.label ?? s.symbol}
                </option>
              ))}
            </select>

            <select value={timeframe} onChange={e => setTimeframe(e.target.value)} className="bg-gray-700 text-gray-100 p-2 rounded">
              <option value="1h">1h</option>
              <option value="4h">4h</option>
              <option value="1d">1d</option>
            </select>
          </div>
        </div>

        <div className="bg-gray-800 p-6 rounded shadow mb-6">
          <div className="mb-3">
            <strong>Latest prediction</strong>
            <div>
              {prediction && Number.isFinite(prediction.pred_next_1h_return)
                ? `${(prediction.pred_next_1h_return*100).toFixed(3)}% — P(up) ${(prediction.pred_prob_up*100).toFixed(1)}%`
                : (prediction?.error ? `Error: ${prediction.error}` : "No prediction")
              }
            </div>
          </div>

          <div>
            <strong>Price chart</strong>
            {loading ? <div>Loading OHLCV…</div> :
              ohlcv.length ? (
                <div style={{height: 360}}>
                  <Line data={data} />
                </div>
              ) : <div>No OHLCV data</div>
            }
          </div>
        </div>

        <div className="bg-gray-800 p-6 rounded shadow">
          <strong>Equity plot</strong>
          <div>
            <BacktestImage />
          </div>
        </div>
      </div>
    </div>
  );
}

function BacktestImage(){
  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const [imgUrl, setImgUrl] = useState(null);
  useEffect(()=>{
    (async ()=>{
      try{
        const res = await fetch(`${API}/market/backtest/latest`);
        if(!res.ok) return;
        const j = await res.json();
        if(j.file){
          const raw = await fetch(`${API}/market/backtest/raw?file=${encodeURIComponent(j.file)}`);
          if(raw.ok){
            const blob = await raw.blob();
            setImgUrl(URL.createObjectURL(blob));
          }
        }
      }catch(e){
        console.error(e);
      }
    })();
  },[]);
  if(!imgUrl) return <div>No backtest image available</div>;
  return <img src={imgUrl} style={{width:"100%", maxHeight:400, objectFit:"contain"}} />;
}
