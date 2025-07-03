# Backend Development Instructions

## Base Instructions
- Build a modular Flask backend using blueprints for scalable and maintainable feature development.
- Use SQLAlchemy ORM with polymorphic inheritance to support flexible and extensible data models.
- Expose RESTful API endpoints for seamless frontend-backend communication.

## Features

### Stock Models
- **Base Stock Model**:  
  - Properties:  
    - `symbol`: Stock symbol (e.g., AAPL, TSLA)
    - `name`: Full name of the stock
    - `description`: Description of the stock
    - `type`: Type of the stock (e.g., Index, ETF, Equity)
    - `price`: Current price
    - `volume`: Trading volume
    - `change`: Change in price
    - `change_percent`: Percentage change in price
    - `currency`: Currency (e.g., USD, EUR)
    - `risk_level`: Risk level (e.g., low, medium, high)
    - `tag`: Label or category (e.g., technology, healthcare)
    - `note`: Notes or comments

- **Equity Model** (inherits from Base Stock):  
  - Additional properties:  
    - `sector`: Sector (e.g., Technology, Healthcare)
    - `industry`: Industry (e.g., Software, Pharmaceuticals)
    - `market_cap`: Market capitalization
    - `eps`: Earnings per share
    - `forward_pe`: Forward price-to-earnings ratio
    - `pe_ratio`: Price-to-earnings ratio
    - `peg_ratio`: Price/earnings-to-growth ratio
    - `dividend_yield`: Dividend yield percentage

- **Index Model** (inherits from Base Stock):  
  - Additional properties:  
    - `top_holdings`: List or relationship of constituent stocks

### Watchlist & Portfolio Models
- **WatchList Model** (base):  
  - Supports polymorphic inheritance for different watchlist types (e.g., standard, portfolio, custom)
  - Represents a collection of stocks
  - Properties:  
    - `name`: Watchlist name
    - `description`: Description
    - `type`: Watchlist type
    - `tag`: Label or category
    - `note`: Notes or comments

- **Portfolio Model** (inherits from WatchList):  
  - Represents a collection of stocks with quantities
  - Additional properties:  
    - `total_value`: Sum of (current price × quantity) for all stocks
    - `total_change`: Total change in portfolio value
    - `total_change_percent`: Total percentage change

## API & Architecture
- Organize Flask code using blueprints and the application factory pattern for maintainability and scalability.
- Implement RESTful API endpoints for all CRUD operations on stocks, watchlists, and portfolios.
- Use Marshmallow or similar for serialization and input validation.
- Ensure all endpoints have comprehensive error handling and return clear, consistent JSON responses.
- Use environment variables for all configuration and secrets (never hardcode sensitive data).
- Prepare for future authentication and authorization (e.g., JWT, OAuth2).

## Guidelines & Best Practices
- Use Python 3.10+ and follow PEP 8 style guide.
- Create and activate a Python virtual environment for backend development.
- Prevent SQL injection by using SQLAlchemy’s ORM and parameterized queries.
- Write clear, concise, and well-documented code with docstrings and comments.
- Organize code into logical modules: models, schemas, routes, services, and tests.
- Write unit and integration tests for all critical logic and API endpoints.
- Use version control (git) with clear commit messages and feature branches.
- Ensure code is ready for containerization (e.g., Docker) and deployment.
- Document API endpoints and data models (e.g., with Swagger/OpenAPI).
- Use linters (e.g., flake8) and formatters (e.g., black) to maintain code quality.
- Default Indexes: S&P 500, NASDAQ-100, Dow Jones Industrial Average
- Default ETFs: SPY, QQQ, DIA
- Default Stocks: AAPL, TSLA, MSFT, AMZN, GOOGL, META, NVDA
  - These should be pre-populated in the database for development and testing.
  - Ensure each default entity includes realistic sample data for all required model fields.
  - Use these as reference examples for API responses and documentation.