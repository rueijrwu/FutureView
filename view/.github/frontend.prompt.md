# Frontend Development Instructions

## Base Instructions
- Build the full MVP in the current folder (do not create a new folder). Don stop until it is done.
- This is a frontend-only web app for now, but will connect to a backend in the future.
- For the MVP, both Portfolio and Watchlist pages will display only one ticker (AAPL), with data fetched once from Yahoo Finance and hardcoded in the frontend.

## Features
- Create a modern React dashboard app with a sidebar for navigation.
- Use Vite for fast development and hot module reloading.
- Use Dark theme by default. 
- The dashboard should display K-line (candlestick) daily charts for major US indexes: S&P 500, NASDAQ, Dow Jones, and IWM.
    - Use the latest TradingView Lightweight Charts for all chart visualizations.
    - Add a "Market Overview" section showing key macro indicators:
    - Display real-time or daily updated values for VIX, US 10-Year Treasury Yield, and Dollar Index (DXY).
    - Show a heatmap of sector performance (e.g., S&P 500 sectors) with color-coded gain/loss.
    - Include a summary of major global indexes (e.g., FTSE, DAX, Nikkei) with current values and daily change.
    - Provide a simple economic calendar highlighting upcoming major US economic events (e.g., FOMC, CPI, jobs report).
    - Visualize market breadth indicators (e.g., advance/decline line, % of stocks above 50/200 MA).
- Sidebar navigation links:
    - Home
    - Portfolio
    - Watchlist
    - Settings
- Portfolio page:
    - Display a table with columns: Ticker, Current Value, Cost, Date of Purchase, Due Date (if option), Latest Note, Quantity, Average Cost, Total Return, % Return, Sector, Asset Type, Portfolio Allocation
    - Allow users to add, edit, or remove positions (including updating notes and purchase details)
    - Show a summary section with total portfolio value, total gain/loss, and allocation by sector/asset type
    - Visualize portfolio allocation with a pie or donut chart
    - Enable sorting and filtering of the table by any column
    - Provide quick links to financial news and company profiles for each holding
    - Ensure the table is responsive and accessible on all devices
    - Use clear formatting and responsive design for the table
- Watchlist page:
    - Display a table with columns: Ticker, Price, Volume, Change, 52-Week High, 52-Week Low, Market Cap, P/E Ratio, Dividend Yield, Analyst Rating
    - Allow users to add or remove tickers from the watchlist
    - Enable sorting and filtering of the table by any column
    - Show a small sparkline chart for each ticker's recent price trend
    - Provide quick links to financial news and company profiles for each ticker
    - Allow users to add personal notes for each watched stock
    - Ensure the table is easy to read and mobile-friendly
- Settings page:
    - Leave empty for now, but structure the route/component for future expansion

## Guidelines
- Use TypeScript for all React code
- Use the latest stable versions of React, Vite, and TradingView Lightweight Charts
- Keep the dashboard layout simple and modular to allow for future redesigns
- Use functional components and React hooks for state management
- Organize code with clear folder structure (e.g., components, pages, utils)
- Write clean, well-documented, and maintainable code
- Ensure the UI is responsive and accessible (basic ARIA roles, keyboard navigation)
- Use environment variables for configuration (e.g., API keys, endpoints) if needed
- Prepare for easy integration with backend APIs in the future (e.g., use fetch/axios with mock data for now)
- Use ESLint and Prettier for code quality and formatting

## Optional Enhancements (for future sprints)
- Add user authentication and session management
- Enable real-time data updates via WebSocket or polling
- Add dark mode and theme customization
- Implement advanced chart features (indicators, drawing tools)
- Add notifications or alerts for portfolio/watchlist changes
