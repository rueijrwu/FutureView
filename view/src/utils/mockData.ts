// Hardcoded mock data for AAPL and market overview for MVP

export const aaplPortfolio = [
  {
    ticker: 'AAPL',
    currentValue: 21000,
    cost: 18000,
    dateOfPurchase: '2024-01-15',
    dueDate: '',
    latestNote: 'Strong earnings, holding.',
    quantity: 100,
    averageCost: 180,
    totalReturn: 3000,
    percentReturn: 16.7,
    sector: 'Technology',
    assetType: 'Equity',
    allocation: 100,
  },
];

export const aaplWatchlist = [
  {
    ticker: 'AAPL',
    price: 210,
    volume: 120000000,
    change: '+1.2%',
    high52w: 220,
    low52w: 150,
    marketCap: '3.2T',
    peRatio: 32,
    dividendYield: '0.5%',
    analystRating: 'Buy',
    note: 'Watch for next product launch.',
    sparkline: [200, 202, 205, 207, 210, 208, 210],
  },
];

export const marketOverview = {
  vix: 13.2,
  treasury10y: 4.25,
  dxy: 104.5,
  sectors: [
    { name: 'Technology', change: 1.2 },
    { name: 'Healthcare', change: -0.5 },
    { name: 'Financials', change: 0.8 },
    { name: 'Energy', change: -1.1 },
    { name: 'Consumer', change: 0.3 },
    { name: 'Industrials', change: 0.6 },
    { name: 'Utilities', change: -0.2 },
    { name: 'Materials', change: 0.4 },
    { name: 'Real Estate', change: -0.7 },
    { name: 'Comm Services', change: 1.0 },
  ],
  globalIndexes: [
    { name: 'FTSE', value: 7800, change: '+0.4%' },
    { name: 'DAX', value: 16200, change: '-0.2%' },
    { name: 'Nikkei', value: 39000, change: '+0.8%' },
  ],
  economicEvents: [
    { date: '2025-07-03', event: 'FOMC Minutes' },
    { date: '2025-07-10', event: 'CPI Release' },
    { date: '2025-07-15', event: 'Jobs Report' },
  ],
  breadth: {
    advDecline: 1.3,
    above50ma: 62,
    above200ma: 54,
  },
};
