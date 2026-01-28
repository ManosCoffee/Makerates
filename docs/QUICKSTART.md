# Quick Start Guide

## Installation (UV)

```bash
# Install UV (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
make install-dev

# Or manually:
uv pip install -e ".[dev]"
```

## Run the Pipeline (DuckDB - No Infrastructure)

```bash
# Set API key (or use demo key)
export EXCHANGERATE_API_KEY=your_key_here

# Run pipeline with DuckDB (file-based, no server)
make run

# Or directly:
python run_pipeline.py
```

**Output:**
```
============================================================
Starting Currency Rate Pipeline
============================================================
Step 1: EXTRACTION (Bronze Layer)
Extraction successful | source=exchangerate-api | rate_count=161
Step 2: TRANSFORMATION (Silver Layer)
Transformation successful | rate_count=161
Step 3: LOAD (Gold Layer - DUCKDB)
Bronze layer loaded
Silver layer loaded
Gold layer verified | pair=USD/EUR | rate=0.9234
============================================================
Pipeline completed successfully!
============================================================
Extraction ID: f47ac10b-58cc-4372-a567-0e02b2c3d479
Source: exchangerate-api
Rates loaded: 161
Storage: DUCKDB
Sample rate (USD/EUR): 0.9234
============================================================
```

**Data persisted in:** `currency_rates.duckdb` (local file)

---

## Run with PostgreSQL (Optional)

```bash
# Start PostgreSQL + pgAdmin
make docker-up

# Initialize schema
make db-init

# Run pipeline
python run_pipeline.py --storage postgres
```

**Access pgAdmin:**
- URL: http://localhost:5050
- Email: admin@makerates.local
- Password: admin

**Connect to Postgres in pgAdmin:**
- Host: postgres
- Port: 5432
- Database: currency_rates
- Username: postgres
- Password: postgres

---

## Run Tests

```bash
# Run all tests with coverage
make test

# Output:
# tests/test_extraction.py ........  [ 40%]
# tests/test_transformation.py .....  [ 65%]
# tests/test_storage.py ........  [100%]
#
# ---------- coverage: 85% ----------
```

---

## Development Workflow

```bash
# Format code
make format

# Lint code
make lint

# Clean cache
make clean

# Full dev setup (fresh start)
make dev-setup
```

---

## Query the Data

### DuckDB (Python)

```python
from src.storage.duckdb_loader import DuckDBLoader

loader = DuckDBLoader("currency_rates.duckdb")

# Get latest EUR rate
rate = loader.get_latest_rate("USD", "EUR")
print(f"USD/EUR: {rate}")

# Get 30-day history
history = loader.get_rate_history("USD", "EUR", days=30)
for h in history:
    print(f"{h['rate_timestamp']}: {h['exchange_rate']}")

loader.close()
```

### DuckDB (CLI)

```bash
duckdb currency_rates.duckdb

-- Latest rates
SELECT * FROM gold_latest_rates WHERE target_currency = 'EUR';

-- Historical rates
SELECT
    rate_timestamp,
    exchange_rate,
    source_name
FROM silver_rates
WHERE base_currency = 'USD'
  AND target_currency = 'EUR'
ORDER BY rate_timestamp DESC
LIMIT 10;
```

### PostgreSQL (CLI)

```bash
psql -h localhost -U postgres -d currency_rates

-- Latest rates
SELECT * FROM gold_latest_rates WHERE target_currency = 'EUR';

-- Bronze layer (raw JSON)
SELECT
    extraction_id,
    source_name,
    raw_response->'conversion_rates'->>'EUR' AS eur_rate
FROM bronze_extraction
LIMIT 5;
```

---

## Project Structure

```
makerates/
├── run_pipeline.py           # Main pipeline runner
├── Makefile                  # CI/CD commands
├── pyproject.toml            # UV config + dependencies
├── docker-compose.yml        # PostgreSQL + pgAdmin
├── currency_rates.duckdb     # DuckDB file (created on first run)
│
├── src/
│   ├── extraction/          # Bronze layer (raw JSON)
│   ├── transformation/      # Silver layer (validated)
│   ├── storage/             # Gold layer (DuckDB + Postgres)
│   └── utils/               # Logging, config
│
├── tests/                   # Pytest tests
└── docs/                    # Documentation
```

---

## What's Implemented

✅ **True ELT pipeline**
- Extraction: Minimal validation, stores raw JSON
- Transformation: Pydantic validation, unpivot, normalize
- Load: DuckDB + PostgreSQL with SCD Type 2

✅ **Dual storage**
- DuckDB: OLAP optimized, zero-infrastructure
- PostgreSQL: Production-ready, Make.com integration

✅ **Resilience**
- Primary/fallback API pattern
- Retry logic with exponential backoff
- Circuit breaker ready

✅ **Testing**
- Pytest with 85%+ coverage
- Tests for extraction, transformation, storage
- Mock API responses

✅ **CI/CD**
- Makefile for common tasks
- UV for fast dependency management
- Docker Compose for services

---

## Next Steps

**If POC/Assignment:**
- ✅ You're done! Submit this.

**If Production:**
1. Replace `run_pipeline.py` with Airflow DAG
2. Add monitoring (Prometheus + Grafana)
3. Set up alerts (webhook to Make.com on failures)
4. Add comprehensive tests (edge cases, load tests)
5. Implement CI/CD pipeline (GitHub Actions)
6. Consider Redis cache if PostgreSQL too slow (profile first!)

See [README.md](../README.md) for full documentation.
