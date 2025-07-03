# US Stock Investment Full Stack Web Application

This is a robust, full stack web application for real-time US stock and portfolio management.

- **Backend:** Flask as the web framework, following modular design principles.
- **Database:** SQLAlchemy ORM with SQLite for development (easily switchable to other RDBMS for production).
- **Templating:** Jinja2 for server-side HTML rendering.
- **Frontend:** React (TypeScript) app for a dynamic, responsive client-side experience.
- **Visualization:** TradingView Lightweight Charts for interactive financial data visualization.
- **UI/UX:** Dashboard interface with a sidebar for seamless navigation across multiple features.

## Key Components
- Modular Flask backend with blueprints for scalable feature development
- SQLAlchemy models with polymorphic inheritance for flexible data structures
- RESTful API endpoints for frontend-backend communication
- React dashboard with reusable components and state management
- Real-time data updates and visualizations
- User authentication and session management (planned/optional)

## Development Guidelines

- Create and activate a Python virtual environment for backend development
- Build a full MVP before adding advanced features
- Use Vite for fast frontend development and hot module reloading
- Follow PEP 8 standards for all Python code
- Organize Flask code using blueprints and application factory patterns for maintainability
- Prevent SQL injection by using SQLAlchemy's ORM features and parameterized queries
- Implement comprehensive error handling in all route and service functions
- Ensure responsive design and cross-device compatibility for all UI changes
- Write clear, concise, and well-documented code for both backend and frontend
- Use environment variables for configuration and secrets (never hardcode sensitive data)
- Write unit and integration tests for critical backend and frontend logic
- Use version control (git) with clear commit messages and feature branches

## Tools

- When asked to use Playwright, do not edit or run files. Only run Playwright commands as instructed.
- When using Playwright tools, assume the application is already running and accessible.
- Use linters (e.g., flake8 for Python, ESLint for TypeScript) and formatters (e.g., black, prettier) to maintain code quality

## Contribution

- Submit pull requests with clear descriptions and reference related issues
- Review code for security, performance, and readability before merging
- Communicate major changes with the team and update documentation as needed

##
