import React from 'react';
import CandlestickChart from '../components/CandlestickChart';
import { marketOverview } from '../utils/mockData';

// Example hardcoded candlestick data for S&P 500 (replace with real data as needed)
const sp500Data = [
  { time: '2025-06-23', open: 5400, high: 5450, low: 5380, close: 5430 },
  { time: '2025-06-24', open: 5430, high: 5470, low: 5410, close: 5460 },
  { time: '2025-06-25', open: 5460, high: 5480, low: 5440, close: 5450 },
  { time: '2025-06-26', open: 5450, high: 5490, low: 5430, close: 5480 },
  { time: '2025-06-27', open: 5480, high: 5500, low: 5460, close: 5495 },
];

const Home: React.FC = () => {
  return (
    <div>
      <h1>Market Dashboard</h1>
      <section>
        <h2>S&P 500</h2>
        <CandlestickChart data={sp500Data} width={600} height={300} />
      </section>
      <section>
        <h2>Market Overview</h2>
        <div style={{ display: 'flex', gap: '2rem' }}>
          <div>
            <strong>VIX:</strong> {marketOverview.vix}
          </div>
          <div>
            <strong>US 10Y:</strong> {marketOverview.treasury10y}%
          </div>
          <div>
            <strong>DXY:</strong> {marketOverview.dxy}
          </div>
        </div>
      </section>
      {/* Add more charts and sections for NASDAQ, Dow Jones, IWM, heatmap, global indexes, etc. */}
    </div>
  );
};

export default Home;
