# MakeRates Data Inspection Guide

This guide provides copy-paste commands to query data at each layer of the pipeline.

**Prerequisites**: Pipeline has run at least once via Kestra

---

## Quick Reference

| Layer | Query Tool | Example Command |
|-------|------------|-----------------|
| Bronze (S3 JSONL) | AWS CLI | `aws s3 ls s3://bronze-bucket/... --endpoint-url http://localhost:9000` |
| Silver (Iceberg) | DuckDB | `iceberg_scan('s3://silver-bucket/iceberg/default/frankfurter_rates')` |
| Gold (DuckDB) | DuckDB | `SELECT * FROM mart_latest_rates` |

---

## Bronze Layer (Raw JSONL on MinIO S3)

### List Bronze Files

```bash
# Frankfurter rates
aws s3 ls s3://bronze-bucket/frankfurter/rates/daily/ \
    --recursive \
    --endpoint-url http://localhost:9000 \
    --no-sign-request | tail -10

# ExchangeRate-API rates
aws s3 ls s3://bronze-bucket/exchangerate/rates/daily/ \
    --recursive \
    --endpoint-url http://localhost:9000 \
    --no-sign-request | tail -10

# CurrencyLayer rates
aws s3 ls s3://bronze-bucket/currencylayer/rates/daily/ \
    --recursive \
    --endpoint-url http://localhost:9000 \
    --no-sign-request | tail -10
```

---

### Download & View Raw JSON

```bash
# Set today's date (adjust as needed)
export DATE=$(date +%Y_%m_%d)
export YEAR=$(date +%Y)
export MONTH=$(date +%m)

# Download Frankfurter sample file
aws s3 cp s3://bronze-bucket/frankfurter/rates/daily/${YEAR}/${MONTH}/${DATE}/ /tmp/bronze_sample/ \
    --recursive \
    --endpoint-url http://localhost:9000 \
    --no-sign-request

# View raw JSONL (first 50 lines)
zcat /tmp/bronze_sample/*.jsonl.gz | jq '.' | head -50
```

**Expected Output**:
```json
{
  "extraction_id": "frankfurter_20260128_143022",
  "extraction_timestamp": "2026-01-28T14:30:22.123456Z",
  "source": "frankfurter",
  "source_tier": "primary",
  "base_currency": "EUR",
  "rate_date": "2026-01-28",
  "rates": {
    "USD": 1.0850,
    "GBP": 0.8612,
    "JPY": 156.23
  },
  "http_status_code": 200,
  "response_size_bytes": 1247
}
```

---

## Silver Layer (Iceberg Tables on S3)

### Query Iceberg Tables via DuckDB

```bash
# Connect to DuckDB
duckdb dbt_project/gold.duckdb
```

```sql
-- Load Iceberg extension (if not auto-loaded)
LOAD iceberg;

-- Query Frankfurter Iceberg table
SELECT
    extraction_id,
    source,
    base_currency,
    rate_date,
    rates__USD,  -- Nested column example
    rates__GBP,
    rates__JPY
FROM iceberg_scan('s3://silver-bucket/iceberg/default/frankfurter_rates')
WHERE rate_date >= CURRENT_DATE - INTERVAL '7 DAY'
ORDER BY rate_date DESC
LIMIT 10;

-- Count total records per source
SELECT
    source,
    COUNT(*) as total_records,
    MIN(rate_date) as earliest_date,
    MAX(rate_date) as latest_date,
    COUNT(DISTINCT rate_date) as distinct_dates
FROM iceberg_scan('s3://silver-bucket/iceberg/default/frankfurter_rates')
GROUP BY source;

-- Check all Iceberg tables
SELECT * FROM iceberg_scan('s3://silver-bucket/iceberg/default/exchangerate_rates') LIMIT 5;
SELECT * FROM iceberg_scan('s3://silver-bucket/iceberg/default/currencylayer_rates') LIMIT 5;
```

---

### View Iceberg Metadata (PostgreSQL Catalog)

```bash
# Connect to Iceberg catalog database
docker exec -it makerates-iceberg-db psql -U iceberg -d iceberg_catalog

# List all tables in catalog
\dt

# View Iceberg table metadata
SELECT
    namespace_name,
    table_name,
    metadata_location,
    previous_metadata_location
FROM iceberg_tables;

# Exit PostgreSQL
\q
```

---

## dbt Staging Models (Silver Views)

### Query Staging Views

```bash
duckdb dbt_project/gold.duckdb
```

```sql
-- Frankfurter staging (unpivoted EUR rates)
SELECT
    extraction_id,
    source,
    base_currency,
    target_currency,
    exchange_rate,
    rate_date,
    currency_pair,
    inverse_rate
FROM stg_frankfurter
WHERE rate_date >= CURRENT_DATE - INTERVAL '7 DAY'
ORDER BY rate_date DESC, target_currency
LIMIT 20;

-- ExchangeRate-API staging (unpivoted USD rates)
SELECT * FROM stg_exchangerate
WHERE rate_date >= CURRENT_DATE - INTERVAL '7 DAY'
LIMIT 20;

-- CurrencyLayer staging (unpivoted mixed base rates)
SELECT * FROM stg_currencylayer
WHERE rate_date >= CURRENT_DATE - INTERVAL '7 DAY'
LIMIT 20;
```

---

## Validation Layer (Consensus Check)

### View Flagged Anomalies

```bash
duckdb dbt_project/gold.duckdb
```

```sql
-- Rates flagged by consensus check (>0.5% variance)
SELECT
    rate_date,
    target_currency,
    consensus_rate,
    frank_rate,
    exchangerate_rate,
    currencylayer_rate,
    frank_dev as frankfurt_deviation_pct,
    er_dev as exchangerate_deviation_pct,
    cl_dev as currencylayer_deviation_pct,
    status
FROM consensus_check
WHERE status = 'FLAGGED'
ORDER BY frank_dev DESC
LIMIT 20;

-- If empty result = all rates validated ✅

-- Count flagged rates by currency
SELECT
    target_currency,
    COUNT(*) as flagged_count,
    AVG(frank_dev) as avg_deviation,
    MAX(frank_dev) as max_deviation
FROM consensus_check
WHERE status = 'FLAGGED'
GROUP BY target_currency
ORDER BY flagged_count DESC;
```

---

## Silver Fact Layer

### Query Fact Rates Validated (Single Source of Truth)

```bash
duckdb dbt_project/gold.duckdb
```

```sql
-- Latest validated rates
SELECT
    rate_date,
    currency_pair,
    exchange_rate,
    inverse_rate,
    validation_status,
    severity,
    consensus_variance
FROM fact_rates_validated
WHERE target_currency IN ('USD', 'GBP', 'JPY', 'AUD', 'CAD')
ORDER BY rate_date DESC, target_currency
LIMIT 20;

-- Validation statistics
SELECT
    validation_status,
    severity,
    COUNT(*) as count
FROM fact_rates_validated
WHERE rate_date = (SELECT MAX(rate_date) FROM fact_rates_validated)
GROUP BY validation_status, severity;

-- Currency coverage check
SELECT
    rate_date,
    COUNT(DISTINCT target_currency) as currency_count
FROM fact_rates_validated
WHERE rate_date >= CURRENT_DATE - INTERVAL '7 DAY'
GROUP BY rate_date
ORDER BY rate_date DESC;
```

---

## Gold Layer (Business Analytics - DuckDB)

### List All Gold Tables

```bash
duckdb dbt_project/gold.duckdb
```

```sql
-- Show all tables
SELECT
    table_name,
    table_type
FROM information_schema.tables
WHERE table_schema = 'main'
  AND table_name LIKE 'mart_%' OR table_name LIKE 'dim_%'
ORDER BY table_name;
```

---

### Query Dimensions

```sql
-- Country dimension
SELECT * FROM dim_countries
ORDER BY region, country_name;

-- Count by region
SELECT
    region,
    COUNT(*) as country_count,
    STRING_AGG(currency_code, ', ') as currencies
FROM dim_countries
GROUP BY region;
```

---

### Query Business Marts

#### mart_latest_rates

```sql
-- Latest rates by region
SELECT
    target_currency,
    country_name,
    region,
    exchange_rate,
    inverse_rate,
    consensus_variance,
    validation_status
FROM mart_latest_rates
WHERE region = 'Europe'
ORDER BY target_currency;

-- All latest rates
SELECT * FROM mart_latest_rates
ORDER BY region, target_currency;
```

---

#### mart_currency_conversions (NEW)

```sql
-- USD conversions to other currencies
SELECT
    from_currency,
    to_currency,
    exchange_rate,
    ROUND(100 * exchange_rate, 2) as convert_100_units
FROM mart_currency_conversions
WHERE from_currency = 'USD'
ORDER BY to_currency;

-- Example: Convert 100 USD to EUR, GBP, JPY
SELECT
    to_currency,
    100 * exchange_rate as amount_after_conversion
FROM mart_currency_conversions
WHERE from_currency = 'USD'
  AND to_currency IN ('EUR', 'GBP', 'JPY');

-- Cross-rate matrix (top 5 currencies)
SELECT
    from_currency,
    STRING_AGG(
        to_currency || '=' || ROUND(exchange_rate, 4)::TEXT,
        ', '
        ORDER BY to_currency
    ) as cross_rates
FROM mart_currency_conversions
WHERE from_currency IN ('USD', 'EUR', 'GBP', 'JPY', 'AUD')
GROUP BY from_currency;
```

---

#### mart_rate_volatility (NEW)

```sql
-- High-risk currencies (most volatile)
SELECT
    target_currency,
    exchange_rate,
    daily_change_pct,
    change_7d_pct,
    change_30d_pct,
    volatility_7d,
    risk_level
FROM mart_rate_volatility
WHERE rate_date = (SELECT MAX(rate_date) FROM mart_rate_volatility)
  AND risk_level = 'HIGH_RISK'
ORDER BY ABS(daily_change_pct) DESC
LIMIT 10;

-- Stable currencies
SELECT
    target_currency,
    daily_change_pct,
    change_7d_pct,
    risk_level
FROM mart_rate_volatility
WHERE rate_date = (SELECT MAX(rate_date) FROM mart_rate_volatility)
  AND risk_level = 'STABLE'
ORDER BY target_currency;

-- Volatility trend over time (last 30 days)
SELECT
    rate_date,
    target_currency,
    daily_change_pct,
    risk_level
FROM mart_rate_volatility
WHERE target_currency = 'GBP'
  AND rate_date >= CURRENT_DATE - INTERVAL '30 DAY'
ORDER BY rate_date DESC;
```

---

#### mart_data_quality_metrics (NEW)

```sql
-- Pipeline health dashboard
SELECT
    'Last Extraction:' as metric,
    CAST(last_extraction AS VARCHAR) as value
UNION ALL
SELECT 'Last Rate Date:', CAST(last_rate_date AS VARCHAR)
UNION ALL
SELECT 'Hours Since Extraction:', CAST(hours_since_extraction AS VARCHAR)
UNION ALL
SELECT 'Days Since Rate:', CAST(days_since_rate AS VARCHAR)
UNION ALL
SELECT 'Currency Count:', CAST(currency_count AS VARCHAR)
UNION ALL
SELECT 'Total Records:', CAST(total_records AS VARCHAR)
UNION ALL
SELECT 'OK Rate:', CAST(ROUND(ok_rate * 100, 2) AS VARCHAR) || '%'
UNION ALL
SELECT 'Flagged Count:', CAST(flagged_count AS VARCHAR)
UNION ALL
SELECT 'Pipeline Status:', pipeline_status
FROM mart_data_quality_metrics;

-- Single query view
SELECT * FROM mart_data_quality_metrics;
```

**Expected**:
- `pipeline_status = 'HEALTHY'`
- `ok_rate >= 0.90`
- `days_since_rate <= 2`
- `currency_count >= 100`

---

#### mart_monthly_summary (NEW)

```sql
-- Current year monthly summary
SELECT
    month,
    target_currency,
    sample_count,
    ROUND(min_rate, 4) as min_rate,
    ROUND(max_rate, 4) as max_rate,
    ROUND(avg_rate, 4) as avg_rate,
    ROUND(volatility_pct * 100, 2) as volatility_pct,
    ROUND(opening_rate, 4) as opening_rate,
    ROUND(closing_rate, 4) as closing_rate
FROM mart_monthly_summary
WHERE year = YEAR(CURRENT_DATE)
  AND target_currency IN ('USD', 'GBP', 'JPY')
ORDER BY month DESC, target_currency;

-- Year-over-year comparison (USD only)
SELECT
    year,
    month_num,
    ROUND(avg_rate, 4) as avg_usd_rate,
    ROUND(volatility_pct * 100, 2) as volatility_pct
FROM mart_monthly_summary
WHERE target_currency = 'USD'
ORDER BY year DESC, month_num DESC
LIMIT 24;  -- Last 2 years
```

---

## DynamoDB Hot Tier (Optional)

### Query DynamoDB Tables

```bash
# Scan currency_rates table (first 10 items)
aws dynamodb scan \
    --table-name currency_rates \
    --endpoint-url http://localhost:8000 \
    --max-items 10

# Query specific currency pair
aws dynamodb query \
    --table-name currency_rates \
    --key-condition-expression "currency_pair = :pair" \
    --expression-attribute-values '{":pair": {"S": "EUR/USD"}}' \
    --endpoint-url http://localhost:8000

# Query by target currency (using GSI)
aws dynamodb query \
    --table-name currency_rates \
    --index-name target_currency-rate_date-index \
    --key-condition-expression "target_currency = :curr" \
    --expression-attribute-values '{":curr": {"S": "USD"}}' \
    --endpoint-url http://localhost:8000
```

---

## MinIO Console (Web UI)

### Browse Bronze/Silver Data

1. **Open browser**: http://localhost:9001
2. **Login**: `minioadmin` / `minioadmin123`
3. **Navigate**:
   - **bronze-bucket** → `frankfurter/rates/daily/` → View JSONL files by date
   - **silver-bucket/iceberg** → View Iceberg Parquet files + metadata

---

## Kestra UI (Workflow Monitoring)

### View Execution Logs

1. **Open browser**: http://localhost:8080
2. **Login**: `admin@kestra.io` / `Kestra123`
3. **Navigate**: **Executions** → Select execution → Click task → **Logs** tab

**Useful logs to check**:
- `transform_silver` → dbt run output
- `create_iceberg_sources` → Compaction statistics
- `extract_parallel` → Extraction counts

---

## Quick Decision Tree

**"Which layer should I query?"**
- **Bronze**: Only for debugging extraction (raw API responses)
- **Silver Iceberg**: Debugging dbt staging models (unpivoted data)
- **Silver Fact** (`fact_rates_validated`): Downstream integrations, DynamoDB sync
- **Gold Marts**: Everything else (analytics, dashboards, reports)

**"How to check if pipeline is healthy?"**
```sql
SELECT * FROM mart_data_quality_metrics;
```

**"How to find bad data?"**
```sql
SELECT * FROM consensus_check WHERE status = 'FLAGGED';
```

**"How to see latest rates?"**
```sql
SELECT * FROM mart_latest_rates LIMIT 10;
```

**"How to convert currencies?"**
```sql
SELECT * FROM mart_currency_conversions
WHERE from_currency = 'USD' AND to_currency = 'EUR';
```

**"Which currencies are volatile?"**
```sql
SELECT * FROM mart_rate_volatility
WHERE risk_level IN ('HIGH_RISK', 'MEDIUM_RISK')
ORDER BY rate_date DESC, ABS(daily_change_pct) DESC;
```

---

## Summary

**Most Common Queries**:

```sql
-- 1. Pipeline health check
SELECT * FROM mart_data_quality_metrics;

-- 2. Latest rates
SELECT * FROM mart_latest_rates LIMIT 20;

-- 3. Currency conversion
SELECT * FROM mart_currency_conversions
WHERE from_currency = 'USD';

-- 4. Volatility analysis
SELECT * FROM mart_rate_volatility
WHERE risk_level = 'HIGH_RISK';

-- 5. Check for anomalies
SELECT * FROM consensus_check WHERE status = 'FLAGGED';
```

**Data Layers**:
1. **Bronze** (MinIO S3): Raw JSONL from APIs
2. **Silver** (Iceberg): Compacted Parquet, normalized schemas
3. **Gold** (DuckDB): Business-ready analytics tables

**Tools**:
- **AWS CLI**: Query Bronze S3 buckets
- **DuckDB**: Query Silver Iceberg + Gold tables
- **PostgreSQL**: View Iceberg catalog metadata
- **MinIO Console**: Browse files (Web UI)
- **Kestra UI**: Monitor workflows (Web UI)
