"use client";

import { useEffect, useState } from "react";
import { predict, fetchBacktestLatest } from "../../lib/api";
import Loader from "../components/Loader";

export default function PredictorPage() {
  const [loading, setLoading] = useState(false);
  const [prediction, setPrediction] = useState(null);
  const [equityCsvUrl, setEquityCsvUrl] = useState(null);
  const [equityImageUrl, setEquityImageUrl] = useState(null);

  async function fetchPrediction() {
    setLoading(true);
    try {
      const json = await predict("BTC/USDT", "1h", false);
      setPrediction(json);
    } catch (e) {
      setPrediction({ error: String(e) });
    } finally {
      setLoading(false);
    }
  }

  async function fetchBacktest() {
    try {
      const { blob, contentType } = await fetchBacktestLatest();
      const url = URL.createObjectURL(blob);
      if (contentType && contentType.includes("image")) {
        setEquityImageUrl(url);
        setEquityCsvUrl(null);
      } else {
        setEquityCsvUrl(url);
        setEquityImageUrl(null);
      }
    } catch (e) {
      setEquityImageUrl(null);
      setEquityCsvUrl(null);
    }
  }

  useEffect(() => {
    fetchPrediction();
    fetchBacktest();
    const i = setInterval(fetchPrediction, 30000);
    return () => clearInterval(i);
  }, []);

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 p-6 flex flex-col items-center">
      <div className="max-w-3xl w-full">
        <h1 className="text-3xl font-semibold mb-4">
          Predictor — BTC/USDT (1h)
        </h1>

        <div className="bg-gray-800 rounded-2xl p-6 shadow-xl">
          {loading ? (
            <div className="text-gray-300"><Loader /></div>
          ) : prediction ? (
            prediction.error ? (
              <div className="text-red-400">Error: {prediction.error}</div>
            ) : (
              <>
                <div className="flex justify-between items-center mb-4">
                  <div>
                    <div className="text-sm text-gray-400">Model</div>
                    <div className="text-lg font-medium">
                      {prediction.model_version}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      {prediction.ts}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm text-gray-400">
                      Predicted 1h return
                    </div>
                    <div className="text-2xl font-bold">
                      {Number.isFinite(prediction.pred_next_1h_return)
                        ? `${(prediction.pred_next_1h_return * 100).toFixed(
                            3
                          )}%`
                        : "—"}
                    </div>
                    <div className="text-sm text-green-400">
                      {Number.isFinite(prediction.pred_prob_up)
                        ? `P(up): ${(prediction.pred_prob_up * 100).toFixed(
                            1
                          )}%`
                        : "P(up): —"}
                    </div>
                  </div>
                </div>
                <p className="text-sm text-gray-400">{prediction.note || ""}</p>
              </>
            )
          ) : (
            <div className="text-gray-400">No prediction yet</div>
          )}

          <div className="mt-6 flex gap-3">
            <button
              className="px-4 py-2 bg-rose-500 hover:bg-rose-600 rounded-md"
              onClick={fetchPrediction}
            >
              Refresh
            </button>
            {equityCsvUrl && (
              <a
                href={equityCsvUrl}
                download={`equity_${Date.now()}.csv`}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-md"
              >
                Download latest equity CSV
              </a>
            )}
          </div>
        </div>

        <div className="mt-6 bg-gray-800 rounded-2xl p-4 shadow-lg">
          <h2 className="text-lg font-medium mb-2">Latest equity plot</h2>
          {equityImageUrl ? (
            <img
              src={equityImageUrl}
              alt="Equity curve"
              className="w-full h-96 object-contain rounded"
            />
          ) : equityCsvUrl ? (
            <a
              href={equityCsvUrl}
              download={`equity_${Date.now()}.csv`}
              className="text-sm text-gray-400"
            >
              Download equity CSV
            </a>
          ) : (
            <div className="text-gray-400">No backtest plot available</div>
          )}
        </div>
      </div>
    </div>
  );
}
