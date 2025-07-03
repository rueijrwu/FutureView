import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, CandlestickData as LWCandlestickData } from 'lightweight-charts';

interface CandlestickData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface ChartProps {
  data: CandlestickData[];
  width?: number;
  height?: number;
}

const CandlestickChart: React.FC<ChartProps> = ({ data, width = 400, height = 250 }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;
    chartRef.current = createChart(chartContainerRef.current, {
      width,
      height,
      layout: {
        background: { type: ColorType.Solid, color: '#fff' },
        textColor: '#222',
      },
      grid: { vertLines: { color: '#eee' }, horzLines: { color: '#eee' } },
    });
    // Use CandlestickSeries variable for v5.x
    seriesRef.current = chartRef.current.addSeries(CandlestickSeries);
    if (seriesRef.current) {
      seriesRef.current.setData(data as LWCandlestickData[]);
    }
    return () => chartRef.current?.remove();
  }, [data, width, height]);

  return <div ref={chartContainerRef} />;
};

export default CandlestickChart;
