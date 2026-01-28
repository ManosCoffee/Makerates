# MakeRates - Multi-Currency Data Pipeline

**Data Engineer Home Assignment** - Make.com  
**Architecture**: Medallion (Bronze → Silver Iceberg → Gold DuckDB)  
**Orchestration**: Kestra Workflows

---

## What This Project Does (30-Second Pitch)

A production-ready **ELT pipeline** that:
1. **Extracts** currency rates from 3 external APIs (Frankfurter/ECB, ExchangeRate-API, CurrencyLayer)
2. **Validates** rates using multi-source consensus (flags >0.5% deviations)
3. **Transforms** data with dbt (Silver Iceberg → Gold DuckDB analytics)
4. **Loads** validated rates to DynamoDB hot tier for downstream services

**Business Value**:
- Currency conversion for analytics (reporting revenue in single currency)
- Production verification (audit payment processor rates for accuracy)
- Backup/failover resilience (if production source fails)

**Key Design Choice**: ELT over ETL
- Extract raw JSON with minimal validation → Load to bronze → Transform with full validation
- Enables reprocessing without re-calling APIs (saves cost, enables fixing logic)
- More resilient to API changes (schema changes don't break extraction)

---

## Quick Start for Reviewers (5 Minutes)

### Prerequisites
- Docker & Docker Compose  
- Python 3.12+ with `uv` package manager  
- 8GB RAM, 5GB disk space

### Run the Pipeline

```bash
# 1. Install dependencies
uv pip install -e ".[dev]"

# 2. Start infrastructure (Docker Compose + init DynamoDB)
just run

# 3. Access Kestra UI
open http://localhost:8080
# Login: admin@kestra.io / Kestra123

# 4. Execute workflow
# In Kestra UI:
# - Navigate to "Executions" → "Create Execution"
# - Select flow: "makerates.rates_daily"
# - Set input: execution_date = today's date (YYYY-MM-DD)
# - Click "Execute"

# 5. Monitor execution
# Watch task progress in Kestra UI:
# ✅ check_quotas
# ✅ extract_parallel (Frankfurter, ExchangeRate-API, CurrencyLayer)
# ✅ create_iceberg_sources (Bronze → Iceberg compaction)
# ✅ transform_silver (dbt run + test)
# ✅ sync_to_dynamodb

# 6. Verify results
duckdb dbt_project/gold.duckdb <<EOF
SELECT * FROM mart_data_quality_metrics;
SELECT COUNT(*) FROM mart_latest_rates;
SELECT * FROM mart_rate_volatility WHERE risk_level = 'HIGH_RISK';
EOF
```

**Expected Output**:
- `mart_data_quality_metrics`: pipeline_status = 'HEALTHY', ok_rate >= 0.90
- `mart_latest_rates`: 150+ currency rates
- `mart_rate_volatility`: Risk flags for volatile currencies

---

## Project Architecture

### Data Flow

```
External APIs (Frankfurter, ExchangeRate-API, CurrencyLayer)
        ↓
[BRONZE] dlt → MinIO S3 (Raw JSONL.gz)
    s3://bronze-bucket/{source}/rates/daily/{YYYY}/{MM}/{YYYY_MM_DD}/*.jsonl.gz
        ↓
[COMPACTION] compact_to_iceberg.py (PyIceberg)
    Deduplication: Latest extraction_timestamp per (rate_date, source)
        ↓
[SILVER] Iceberg Tables (S3 Parquet + PostgreSQL Catalog)
    s3://silver-bucket/iceberg/default/frankfurter_rates
    s3://silver-bucket/iceberg/default/exchangerate_rates
    s3://silver-bucket/iceberg/default/currencylayer_rates
        ↓
[dbt TRANSFORM] DuckDB (iceberg_scan → staging → validation → fact)
    - Staging: UNPIVOT rates__* columns → normalized rows
    - Validation: Consensus check (flag >0.5% variance across sources)
    - Fact: fact_rates_validated (single source of truth)
        ↓
[GOLD] DuckDB Tables (Business Analytics)
    - dim_countries
    - mart_latest_rates
    - mart_currency_conversions (cross rates USD/GBP, EUR/JPY)
    - mart_rate_volatility (risk flags)
    - mart_data_quality_metrics (pipeline health)
    - mart_monthly_summary (aggregated reports)
```

### Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Extraction | dlt + Python | API clients with state management |
| Bronze Storage | MinIO S3 | Raw JSONL storage |
| Silver Storage | Apache Iceberg | ACID tables, time travel, Parquet compression |
| Transformation | dbt + DuckDB | SQL-based transformations, OLAP analytics |
| Catalog | PostgreSQL | Iceberg metadata storage |
| Orchestration | Kestra | DAG scheduling, monitoring, UI |
| Hot Tier | DynamoDB | Fast KV lookups for downstream services |
| Containerization | Docker Compose | Local development environment |

---

## Kestra Workflows

### Available Flows

| Flow | Purpose | Trigger | Duration |
|------|---------|---------|----------|
| **rates_daily** | Daily incremental pipeline | Cron: 6 AM UTC | ~5 min |
| **rates_backfill** | Historical data load | Manual | ~20 min |
| **iceberg.yml** | Compact Bronze → Iceberg | Manual | ~2 min |

### Task Execution Flow (rates_daily)

```
1. check_quotas (DynamoDB API tracker)
    ↓
2. extract_parallel (3 sources in parallel)
   ├─ extract_frankfurter (ECB rates → MinIO Bronze)
   ├─ extract_exchangerate (USD rates → MinIO Bronze)
   └─ extract_currencylayer (Failover → MinIO Bronze)
    ↓
3. create_iceberg_sources (Bronze JSONL → Iceberg Parquet)
   ├─ load_frankfurter_to_iceberg
   ├─ load_exchangerate_to_iceberg
   └─ load_currencylayer_to_iceberg
    ↓
4. transform_silver (dbt CLI)
   ├─ dbt deps (Install packages)
   ├─ dbt run (Staging → Validation → Gold)
   └─ dbt test (Data quality checks)
    ↓
5. sync_to_dynamodb (Hot tier upsert)
```

**Kestra Configuration** (kestra/flows/main_makerates.rates_daily.yml):
- **Inputs**: execution_date (DATE), include_currencylayer (BOOLEAN)
- **Environment**: MinIO, DynamoDB, PyIceberg catalog env vars
- **Retry**: 3 attempts with 30s interval for DynamoDB sync
- **Errors**: Centralized error handler with recovery instructions

---

## Running the Project

### Option 1: Kestra UI (Recommended)

1. **Start infrastructure**:
```bash
uv pip install -e ".[dev]"
just run  # Starts Docker Compose + inits DynamoDB
```

2. **Access Kestra UI**: http://localhost:8080 (admin@kestra.io / Kestra123)

3. **Execute workflow**:
   - **Executions** → **Create Execution**
   - Select: `makerates.rates_daily`
   - Input: `execution_date = 2026-01-28` (or leave default for today)
   - Click **Execute**

4. **Monitor tasks**: All tasks should turn green (✅)

5. **View logs**: Click any task → **Logs** tab to see output

---

### Option 2: Manual Execution (For Testing)

Run individual pipeline components inside Docker:

```bash
# 1. Extract (Bronze layer)
docker exec makerates-kestra bash -c "uv run python -m src.frankfurter_to_bronze"

# 2. Compact to Iceberg (Bronze → Silver)
docker exec makerates-kestra bash -c "uv run python -m src.compact_to_iceberg --start-date=2026-01-28"

# 3. Run dbt transformations (Silver → Gold)
docker exec makerates-kestra bash -c "cd /app/dbt_project && dbt run"

# 4. Test data quality
docker exec makerates-kestra bash -c "cd /app/dbt_project && dbt test"
```

**Query Results**:
```bash
# Connect to DuckDB
duckdb dbt_project/gold.duckdb

# Query gold marts
SELECT * FROM mart_latest_rates WHERE target_currency = 'USD';
SELECT * FROM mart_currency_conversions WHERE from_currency = 'USD' AND to_currency = 'EUR';
SELECT pipeline_status, ok_rate, flagged_count FROM mart_data_quality_metrics;
```

---

## Verifying the Pipeline

### 1. Check Kestra Execution Status

In Kestra UI (http://localhost:8080):
- **Executions** → Find your execution
- All tasks should show green checkmarks
- If any task fails, click → **Logs** for error details

### 2. Query Data Quality Metrics

```bash
duckdb dbt_project/gold.duckdb "SELECT * FROM mart_data_quality_metrics;"
```

**Expected**:
- `pipeline_status = 'HEALTHY'`
- `ok_rate >= 0.90` (at least 90% validated)
- `currency_count >= 100`
- `days_since_rate <= 2`

### 3. Check Bronze Layer (MinIO)

```bash
# List Bronze files
aws s3 ls s3://bronze-bucket/frankfurter/rates/daily/ \
    --recursive \
    --endpoint-url http://localhost:9000 \
    --no-sign-request
```

**Expected**: JSONL.gz files for today's date

### 4. Check Silver Iceberg Tables

```bash
duckdb dbt_project/gold.duckdb <<EOF
SELECT COUNT(*) FROM iceberg_scan('s3://silver-bucket/iceberg/default/frankfurter_rates');
EOF
```

**Expected**: >0 rows

### 5. Check Gold Tables

```bash
duckdb dbt_project/gold.duckdb "SHOW TABLES;"
```

**Expected**: 7 tables (1 dim + 6 marts)

---

## Troubleshooting

### Issue: Kestra UI not accessible

**Symptoms**: http://localhost:8080 not loading

**Fix**:
```bash
# Check Docker containers
docker ps | grep kestra

# If not running
just restart-kestra

# View logs
just logs
```

---

### Issue: dbt transform fails with "cannot read iceberg table"

**Symptoms**: Task `transform_silver` fails with "File not found" or "Table does not exist"

**Cause**: Iceberg compaction step (`create_iceberg_sources`) didn't run or failed

**Fix**:
1. Check `create_iceberg_sources` task logs in Kestra UI
2. Ensure Bronze files exist: `aws s3 ls s3://bronze-bucket/frankfurter/ --endpoint-url http://localhost:9000 --no-sign-request`
3. Manually run compaction: `docker exec makerates-kestra bash -c "uv run python -m src.compact_to_iceberg --start-date=2026-01-28"`

---

### Issue: No rates in fact_rates_validated

**Symptoms**: `fact_rates_validated` table is empty or has 0 rows

**Cause**: All rates flagged by consensus check (>0.5% variance)

**Fix**:
```bash
duckdb dbt_project/gold.duckdb <<EOF
-- Check flagged rates
SELECT * FROM consensus_check WHERE status = 'FLAGGED';

-- If many flagged, check Bronze data quality
SELECT * FROM iceberg_scan('s3://silver-bucket/iceberg/default/frankfurter_rates') LIMIT 5;
EOF
```

---

### Issue: Pipeline status shows 'STALE'

**Symptoms**: `mart_data_quality_metrics.pipeline_status = 'STALE'`

**Cause**: No rates loaded in >2 days

**Fix**: Run `rates_daily` workflow with current date

---

## Useful Commands

### justfile Commands

```bash
just run           # Start Docker Compose + init DynamoDB
just reload        # Rebuild worker image + restart Kestra
just init-db       # Initialize DynamoDB tables only
just restart-kestra # Fast Kestra restart
just logs          # View Kestra logs
just clean-start   # Nuclear option (remove volumes + rebuild)
```

### View Services

| Service | URL | Credentials |
|---------|-----|-------------|
| Kestra UI | http://localhost:8080 | admin@kestra.io / Kestra123 |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin123 |
| DuckDB | `duckdb dbt_project/gold.duckdb` | - |

---

## Documentation

- **[SCHEMA_GUIDE.md](SCHEMA_GUIDE.md)** - Comprehensive schema documentation (Bronze → Silver → Gold)
- **[DATA_INSPECTION_GUIDE.md](DATA_INSPECTION_GUIDE.md)** - Query recipes for each layer
- **[docs/](docs/)** - Archived design documentation (⚠️ STALE - refer to codebase)
- **dbt Docs**: Run `dbt docs generate && dbt docs serve` for auto-generated lineage diagrams

---

## Assignment Checklist

### Evaluate market options ✅
- **3 sources identified**: Frankfurter (ECB), ExchangeRate-API, CurrencyLayer
- **Evaluation criteria**: Data quality, coverage, cost, SLA, compliance
- **Risks**: API downtime (mitigated by dual-source), rate inconsistencies (mitigated by consensus validation), quota exhaustion (mitigated by DynamoDB tracker)
- **Thought process**: See [Source Evaluation](#source-evaluation) section

### Develop extraction, transformation, and load modules ✅
- **Extraction**: dlt pipelines (`src/*_to_bronze.py`)
- **Transformation**: dbt models (`dbt_project/models/`)
- **Load**: Iceberg compaction (`src/compact_to_iceberg.py`), DuckDB tables

### Module readiness ✅
- **Tools**: Python, dlt, dbt, DuckDB, Apache Iceberg, Kestra
- **Best practices**: ELT pattern, 4-layer validation (Swiss Cheese), data quality tests, comprehensive documentation

### Deployment and integration ✅
- **Deployment**: Docker Compose (local), Kestra orchestration
- **Broader data model**: Integrates with DynamoDB hot tier, ready for PostgreSQL star schema
- **Communication**: Technical docs (SCHEMA_GUIDE.md), business docs (README.md), demo (Kestra UI)
- **Value**: Multi-currency analytics, payment verification, backup resilience

---

## Source Evaluation

### 3 Currency Rate Sources

| Source | Type | Coverage | Cost | Pros | Cons | Decision |
|--------|------|----------|------|------|------|----------|
| **Frankfurter** | Institutional (ECB) | 30+ currencies | Free, unlimited | Regulatory compliance, high trust | Limited currencies | **Primary Source** |
| **ExchangeRate-API** | Commercial | 161 currencies | Free tier (1500/mo) | Comprehensive coverage | Rate limiting | **Validation Source** |
| **CurrencyLayer** | Commercial | 168 currencies | Free tier (100/mo) | Most comprehensive | Quota-limited | **Fallback Only** |

### Selection Criteria

1. **Data Quality**: Institutional sources (ECB) > commercial aggregators
2. **Coverage**: Need 100+ currencies for global payments
3. **Cost**: Free tier acceptable for POC, paid scales linearly
4. **Reliability**: SLA guarantees (99.9% uptime for paid tiers)
5. **Compliance**: Regulatory data (ECB) required for financial auditing

### Risks Identified

1. **API Downtime**: Mitigated by dual-source architecture (primary + fallback)
2. **Rate Inconsistencies**: Mitigated by consensus validation (flag >0.5% deviations)
3. **Quota Exhaustion**: Mitigated by DynamoDB quota tracker (auto-failover logic)
4. **Schema Changes**: Mitigated by ELT pattern (raw storage enables reprocessing)

---

## ETL vs ELT Decision

### Chosen Approach: ELT (Extract-Load-Transform)

**Rationale**:
1. **Reprocessability**: Store raw API responses → can fix transformation bugs without re-calling APIs (saves cost)
2. **Schema Flexibility**: API schema changes don't break extraction (only transformation)
3. **Audit Trail**: Complete API responses preserved for debugging/compliance
4. **Cost**: External APIs charge per request → reprocessing from storage is free

**Trade-off**: Requires more storage (Bronze layer keeps raw JSON), but S3 storage is cheap ($0.023/GB/month).

---

## Next Steps

For assignment reviewer:
1. ✅ Review this README
2. ✅ Run `just run` to start infrastructure
3. ✅ Execute `rates_daily` workflow in Kestra UI
4. ✅ Query `mart_data_quality_metrics` to verify health
5. ✅ Review [SCHEMA_GUIDE.md](SCHEMA_GUIDE.md) for technical details

For production deployment:
- Activate Kestra triggers (currently manual only)
- Deploy to AWS (Lambda extraction, ECS dbt, RDS PostgreSQL)
- Implement CI/CD (GitHub Actions)
- Add monitoring alerts (Prometheus/Grafana)
- Implement PostgreSQL star schema (if DuckDB insufficient)

---

## Contact & Questions

For questions about this implementation:
- Review [SCHEMA_GUIDE.md](SCHEMA_GUIDE.md) for detailed schema documentation
- Review [DATA_INSPECTION_GUIDE.md](DATA_INSPECTION_GUIDE.md) for query examples
- Check `dbt docs` for lineage diagrams
- Run `just --list` for available commands

**Note**: The `docs/` folder contains legacy documentation from earlier design phases. For current implementation, refer to the codebase, SCHEMA_GUIDE.md, and this README.
