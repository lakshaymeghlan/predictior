"use client";
import { useEffect, useRef } from "react";
import { Chart, registerables } from "chart.js";
import { FinancialController, CandlestickElement } from 'chartjs-chart-financial';
Chart.register(...registerables);
Chart.register(FinancialController, CandlestickElement);

export default function Candlestick({ data, height = 400 }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current) return;
    const ctx = canvasRef.current.getContext("2d");

    const chartData = {
      datasets: [{
        label: "OHLC",
        data: data.map(d => ({
          x: new Date(d.ts).getTime(),
          o: parseFloat(d.open),
          h: parseFloat(d.high),
          l: parseFloat(d.low),
          c: parseFloat(d.close),
        }))
      }]
    };

    const chart = new Chart(ctx, {
      type: "candlestick",
      data: chartData,
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: {
            type: "time",
            time: { tooltipFormat: "yyyy-MM-dd HH:mm" },
          },
          y: {
            ticks: { beginAtZero: false }
          }
        }
      }
    });

    return () => chart.destroy();
  }, [data]);

  return <div style={{ height: height }}><canvas ref={canvasRef}></canvas></div>;
}
