"use client";
import { useEffect, useState } from "react";
import AuthGuard from "../components/AuthGuard";
import { getCurrentUser, predict, fetchBacktestLatest } from "../lib/api";
import Loader from "../components/Loader";

export default function DashboardPage() {
  const [user, setUser] = useState(null);
  const [pred, setPred] = useState(null);
  const [busy, setBusy] = useState(false);
  const [equityUrl, setEquityUrl] = useState(null);

  useEffect(() => {
    const token = localStorage.getItem("PRED_TOKEN");
    if (token) {
      getCurrentUser(token).then(setUser).catch(() => setUser(null));
    }
    refresh();
  }, []);

  async function refresh() {
    setBusy(true);
    try {
      const p = await predict("BTC/USDT", "1h", false);
      setPred(p);
      try {
        const { blob, contentType } = await fetchBacktestLatest();
        const url = URL.createObjectURL(blob);
        setEquityUrl(url);
      } catch (_e) { setEquityUrl(null) }
    } catch (e) {
      setPred({ error: String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthGuard>
      <div>
        <h1 className="text-2xl font-semibold mb-4">Dashboard</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-gray-800 p-6 rounded-2xl">
            <h2 className="text-lg font-medium mb-2">Account</h2>
            {user ? (
              <>
                <div className="text-sm text-gray-400">Email: {user.email}</div>
                <div className="text-sm text-gray-400">Quota remaining: {user.quota_remaining}</div>
              </>
            ) : (
              <div className="text-gray-400">Loading account…</div>
            )}
          </div>

          <div className="bg-gray-800 p-6 rounded-2xl">
            <h2 className="text-lg font-medium mb-2">Latest prediction</h2>
            {busy ? (
              <Loader />
            ) : pred ? (
              pred.error ? (
                <div className="text-rose-400">{pred.error}</div>
              ) : (
                <>
                  <div className="text-sm text-gray-400">Model: {pred.model_version}</div>
                  <div className="text-lg font-bold">{(pred.pred_next_1h_return*100).toFixed(3)}%</div>
                  <div className="text-sm text-green-400">P(up): {(pred.pred_prob_up*100).toFixed(1)}%</div>
                </>
              )
            ) : (
              <div className="text-gray-400">No prediction</div>
            )}
            <div className="mt-4">
              <button onClick={refresh} className="px-4 py-2 bg-rose-500 rounded">Refresh</button>
            </div>
          </div>
        </div>

        <div className="mt-6 bg-gray-800 p-6 rounded-2xl">
          <h2 className="text-lg font-medium mb-2">Equity plot</h2>
          {equityUrl ? (
            <img src={equityUrl} alt="Equity" className="w-full h-96 object-contain rounded" />
          ) : (
            <div className="text-gray-400">No backtest image available</div>
          )}
        </div>
      </div>
    </AuthGuard>
  );
}
