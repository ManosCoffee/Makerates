.PHONY: help install install-dev test lint format run clean docker-up docker-down db-init db-init-star db-init-star-sqlalchemy direnv-check direnv-setup

# Default target
help:
	@echo "Make.com Currency Rate Pipeline - Make Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install       Install production dependencies with uv"
	@echo "  make install-dev   Install all dependencies including dev tools"
	@echo "  make direnv-setup  Setup direnv (recommended for env management)"
	@echo ""
	@echo "Development:"
	@echo "  make test          Run tests with coverage"
	@echo "  make lint          Run linters (ruff, mypy)"
	@echo "  make format        Auto-format code with ruff"
	@echo "  make run           Run the pipeline"
	@echo ""
	@echo "Database:"
	@echo "  make docker-up                  Start PostgreSQL with Docker Compose"
	@echo "  make docker-down                Stop Docker services"
	@echo "  make db-init                    Initialize old database schemas"
	@echo "  make db-init-star               Initialize star schema with psycopg2 (recommended)"
	@echo "  make db-init-star-sqlalchemy    Initialize star schema with SQLAlchemy Core (production)"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean         Remove cache files and artifacts"

# Check if direnv is configured
direnv-check:
	@if ! command -v direnv >/dev/null 2>&1; then \
		echo "⚠️  direnv not installed. Run: make direnv-setup"; \
		exit 1; \
	fi
	@if [ ! -f .envrc ]; then \
		echo "⚠️  .envrc not found. Run: make direnv-setup"; \
		exit 1; \
	fi
	@echo "✅ direnv configured"

# Setup direnv
direnv-setup:
	@echo "Setting up direnv..."
	@if ! command -v direnv >/dev/null 2>&1; then \
		echo "📦 Installing direnv..."; \
		brew install direnv || (echo "❌ Failed. Install manually: https://direnv.net/"; exit 1); \
	fi
	@if [ ! -f .envrc ]; then \
		cp .envrc.example .envrc; \
		echo "✅ Created .envrc from template"; \
	else \
		echo "✅ .envrc already exists"; \
	fi
	@echo ""
	@echo "📝 Next steps:"
	@echo "1. Edit .envrc with your settings"
	@echo "2. Run: direnv allow"
	@echo "3. Add to ~/.zshrc: eval \"\$$(direnv hook zsh)\""
	@echo "4. Restart shell or run: source ~/.zshrc"

# Install production dependencies
install:
	uv pip install -e .

# Install development dependencies
install-dev:
	uv pip install -e ".[dev]"

# Run tests with coverage
test:
	uv run pytest tests/ -v --cov=src --cov-report=term-missing --cov-report=html

# Run linters
lint:
	uv run ruff check src/ tests/
	uv run mypy src/

# Format code
format:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

# Run the pipeline (with direnv check)
run: direnv-check
	uv run python run_pipeline.py

# Clean cache and artifacts
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	rm -f .coverage
	rm -f *.duckdb

# Docker Compose commands
docker-up:
	docker compose up -d
	@echo "Waiting for PostgreSQL to be ready..."
	@sleep 3
	@echo "PostgreSQL is ready at localhost:5432"

docker-down:
	docker compose down

# Initialize database schemas (old schema)
db-init:
	uv run python -c "from src.storage.postgres_loader import PostgresLoader; PostgresLoader().init_schema()"
	@echo "Database schemas initialized"

# Initialize star schema with psycopg2 (recommended for assignment)
db-init-star:
	uv run python -c "from src.storage.postgres_star_loader import PostgresStarLoader; PostgresStarLoader().init_schema()"
	@echo "✅ Star schema initialized successfully (psycopg2)"
	@echo ""
	@echo "Next steps:"
	@echo "1. Run pipeline: make run"
	@echo "2. Query analytics: psql -h localhost -U postgres -d currency_rates"
	@echo "3. See quickstart: cat STAR-SCHEMA-QUICKSTART.md"

# Initialize star schema with SQLAlchemy Core (for production)
db-init-star-sqlalchemy:
	uv run python -c "from src.storage.postgres_star_loader_sqlalchemy import PostgresStarLoaderSQLAlchemy; PostgresStarLoaderSQLAlchemy().init_schema()"
	@echo "✅ Star schema initialized successfully (SQLAlchemy Core)"
	@echo ""
	@echo "Benefits: Connection pooling, Alembic migrations, type safety"
	@echo "See comparison: cat docs/PSYCOPG2-VS-SQLALCHEMY-EXAMPLES.md"

# Quick dev setup (fresh start)
dev-setup: clean install-dev direnv-setup docker-up db-init
	@echo "Development environment ready!"
	@echo "Don't forget to run: direnv allow"
