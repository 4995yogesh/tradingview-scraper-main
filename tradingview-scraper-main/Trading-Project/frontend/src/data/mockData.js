// Mock data for TradingView clone

export const tickerData = [
  { symbol: 'EURUSD', name: 'EUR/USD', price: '1.08142', change: '+0.09%', isUp: true },
];

export const majorIndices = [];

export const cryptoData = [];

export const futuresData = [];

export const forexData = [
  { symbol: 'EURUSD', name: 'EUR/USD', price: '1.08142', change: '+0.09%', isUp: true, status: 'open', sparkline: [50, 51, 50, 52, 51, 53, 52, 51, 53, 52, 54, 53] },
];

export const usStocks = [];

export const communityIdeas = [];

export const topStories = [];

export const brokersData = [
  { name: 'OKX', type: 'Crypto', rating: '4.9', ratingLabel: 'Excellent', featured: true, color: '#000' },
  { name: 'AMP Futures', type: 'Futures', rating: '4.6', ratingLabel: 'Excellent', featured: false, color: '#1a73e8' },
  { name: 'OANDA', type: 'Forex', rating: '4.5', ratingLabel: 'Great', featured: false, color: '#00a0e3', badge: 'Best 2023' },
  { name: 'FOREX.com', type: 'Forex', rating: '4.5', ratingLabel: 'Great', featured: false, color: '#0066cc' },
  { name: 'Interactive Brokers', type: 'Stocks, Crypto, Forex', rating: '4.2', ratingLabel: 'Good', featured: false, color: '#dc143c' },
  { name: 'TradeStation', type: 'Stocks, Futures, Options', rating: '4.3', ratingLabel: 'Good', featured: false, color: '#e31e24', badge: 'Best 2025' },
];

export const navItems = [
  { label: 'Products', hasDropdown: true },
  { label: 'Community', hasDropdown: true },
  { label: 'Markets', hasDropdown: true },
  { label: 'News', hasDropdown: true },
  { label: 'Brokers', hasDropdown: true },
  { label: 'More', hasDropdown: true },
];

export const footerLinks = {
  products: [
    'Supercharts', 'Pine Script', 'Stock Screener', 'ETF Screener',
    'Forex Screener', 'Crypto Screener', 'DEX Screener', 'Stock Heatmap',
    'ETF Heatmap', 'Crypto Heatmap'
  ],
  company: [
    'About', 'Features', 'Pricing', 'Wall of Love',
    'Athletes', 'Manifesto', 'Careers', 'Blog'
  ],
  community: [
    'Refer a friend', 'Ideas', 'Scripts', 'House Rules',
    'Moderators'
  ],
  forBusiness: [
    'Widgets', 'Charting Library', 'Lightweight Charts',
    'Advanced Charts', 'Trading Terminal', 'Brokerage Integration'
  ],
};

export const economicEvents = [
  { time: '08:30', country: 'US', event: 'GDP Growth Rate QoQ', actual: '2.8%', forecast: '2.6%', prior: '3.0%' },
  { time: '10:00', country: 'US', event: 'Consumer Confidence', actual: '-', forecast: '104.5', prior: '104.7' },
  { time: '14:00', country: 'US', event: 'Fed Interest Rate Decision', actual: '-', forecast: '5.25%', prior: '5.25%' },
  { time: '03:00', country: 'DE', event: 'CPI MoM', actual: '-', forecast: '0.3%', prior: '0.2%' },
  { time: '04:00', country: 'GB', event: 'Manufacturing PMI', actual: '48.2', forecast: '47.5', prior: '47.0' },
];

export const marketSummaryChart = [
  { date: 'Jan', value: 5800 },
  { date: 'Feb', value: 5950 },
  { date: 'Mar', value: 5850 },
  { date: 'Apr', value: 6050 },
  { date: 'May', value: 6100 },
  { date: 'Jun', value: 6200 },
  { date: 'Jul', value: 6150 },
  { date: 'Aug', value: 6300 },
  { date: 'Sep', value: 6250 },
  { date: 'Oct', value: 6400 },
  { date: 'Nov', value: 6350 },
  { date: 'Dec', value: 6147 },
];

export const cryptoMarketCap = [
  { date: 'W1', value: 2.1 },
  { date: 'W2', value: 2.15 },
  { date: 'W3', value: 2.08 },
  { date: 'W4', value: 2.2 },
  { date: 'W5', value: 2.25 },
  { date: 'W6', value: 2.18 },
  { date: 'W7', value: 2.28 },
  { date: 'W8', value: 2.3 },
];
