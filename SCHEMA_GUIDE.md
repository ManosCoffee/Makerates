# MakeRates Schema Guide - End-to-End Data Lineage

**Last Updated**: January 2026  
**Architecture**: Medallion (Bronze → Silver Iceberg → Gold DuckDB)

---

## Quick Reference

| Layer | Purpose | Storage | Format | Query Tool | Validation |
|-------|---------|---------|--------|------------|------------|
| **Bronze** | Raw ingestion | MinIO S3 | JSONL.gz | dlt, AWS CLI | None (ELT) |
| **Silver** | Validated rates | S3 + PostgreSQL | Iceberg Parquet | DuckDB via iceberg_scan() | 4-layer Swiss Cheese |
| **Gold** | Business analytics | DuckDB local file | DuckDB tables | duckdb CLI | dbt tests |

---

## Data Flow Architecture

```
External APIs (Frankfurter, ExchangeRate-API, CurrencyLayer)
            ↓
[BRONZE] Raw JSONL on MinIO S3 (dlt pipelines)
    s3://bronze-bucket/{source}/rates/daily/{YYYY}/{MM}/{YYYY_MM_DD}/*.jsonl.gz
            ↓
[COMPACTION] Bronze JSONL → Iceberg Parquet (compact_to_iceberg.py)
    Deduplication on (rate_date, source, base_currency)
    Latest extraction_timestamp wins
            ↓
[SILVER] Iceberg Tables on S3 + PostgreSQL Catalog
    s3://silver-bucket/iceberg/default/frankfurter_rates (Parquet files)
    s3://silver-bucket/iceberg/default/exchangerate_rates
    s3://silver-bucket/iceberg/default/currencylayer_rates
    Catalog: PostgreSQL (makerates-iceberg-db:5433)
            ↓
[dbt STAGING] DuckDB Views (unpivot via iceberg_scan())
    stg_frankfurter → Unpivot rates__* columns → Normalized rows
    stg_exchangerate → Same transformation
    stg_currencylayer → Same transformation
            ↓
[dbt VALIDATION] Consensus Check (incremental table)
    Cross-validate 3 sources, flag >0.5% variance
            ↓
[dbt FACT] fact_rates_validated (materialized table)
    Filter to VALIDATED only, exclude flagged rates
    Single source of truth
            ↓
[GOLD] DuckDB Analytics Tables (7 models)
    dim_countries, mart_latest_rates, mart_currency_conversions,
    mart_rate_volatility, mart_data_quality_metrics, 
    mart_monthly_summary, mart_rate_analysis
```

---

## Bronze Layer (Raw Data Ingestion)

### Storage Architecture

- **Location**: MinIO S3 (local development) or AWS S3 (production)
- **Format**: Newline-delimited JSON (`.jsonl`), gzip compressed
- **Partitioning**: `s3://bronze-bucket/{source}/rates/daily/{YYYY}/{MM}/{YYYY_MM_DD}/*.jsonl.gz`
- **Validation**: **NONE** (true ELT pattern - validate during transformation)

### Data Sources

#### Source 1: Frankfurter (ECB-based)
- **API**: `https://api.frankfurter.app/latest?from=EUR`
- **Base Currency**: EUR (always)
- **Coverage**: 30+ currencies (major economies)
- **Cost**: Free, unlimited
- **Tier**: Primary (institutional ECB data)
- **dlt Pipeline**: `src/frankfurter_to_bronze.py`

**Bronze Schema**:
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
  "api_response_raw": { /* Full API response */ },
  "http_status_code": 200,
  "response_size_bytes": 1247
}
```

**Key Fields**:
- `extraction_id`: Unique per API call (source + timestamp)
- `rates`: Nested object, flattened by dlt to `rates__USD`, `rates__GBP`, etc.
- `api_response_raw`: Complete API response for audit trail

#### Source 2: ExchangeRate-API (USD-based)
- **API**: `https://api.exchangerate-api.com/v4/latest/USD`
- **Base Currency**: USD (always)
- **Coverage**: 161 currencies
- **Cost**: Free tier (1500 req/month)
- **Tier**: Secondary (used for consensus validation)
- **dlt Pipeline**: `src/exchangerate_to_bronze.py`

Similar schema to Frankfurter, but with `"base_currency": "USD"` and `"source": "exchangerate"`.

#### Source 3: CurrencyLayer (Failover)
- **API**: `https://api.currencylayer.com/live`
- **Base Currency**: USD (free tier) or EUR (paid)
- **Coverage**: 168 currencies
- **Cost**: Free tier (100 req/month)
- **Tier**: Secondary (quota-limited, failover only)
- **dlt Pipeline**: `src/currencylayer_to_bronze.py`

---

## Silver Layer (Iceberg Tables on S3)

### Storage Architecture

- **Iceberg Tables**: S3-backed Parquet files with PostgreSQL metadata catalog
- **Location**: `s3://silver-bucket/iceberg/default/{table_name}`
- **Catalog**: PostgreSQL database (makerates-iceberg-db container, port 5433)
- **Format**: Apache Iceberg v2
- **Compaction**: `src/compact_to_iceberg.py` (Bronze JSONL → Iceberg Parquet)

### Iceberg Tables

| Table Name | Location | Source | Purpose |
|------------|----------|--------|---------|
| `frankfurter_rates` | `s3://silver-bucket/iceberg/default/frankfurter_rates` | Frankfurter API | ECB EUR-based rates |
| `exchangerate_rates` | `s3://silver-bucket/iceberg/default/exchangerate_rates` | ExchangeRate-API | USD-based rates |
| `currencylayer_rates` | `s3://silver-bucket/iceberg/default/currencylayer_rates` | CurrencyLayer | Failover source |

### Compaction Process

**Tool**: `compact_to_iceberg.py`

**Steps**:
1. Read all Bronze JSONL files for a date range
2. **Deduplicate** on `(rate_date, source, base_currency)` keeping latest `extraction_timestamp`
3. Convert to PyArrow table
4. **Upsert** into PyIceberg table (ACID transaction)
5. Update PostgreSQL catalog metadata

**Benefits**:
- Parquet compression (10x smaller than JSONL)
- ACID transactions (time travel, schema evolution)
- Deduplication (only latest extraction per day)
- Fast columnar queries (Parquet format)

---

## dbt Staging Models (Silver Layer)

### Purpose
Transform Iceberg tables into normalized, analytics-ready views.

### Read Pattern
All staging models use `iceberg_scan()` to read from Iceberg:

**stg_frankfurter.sql** (lines 18-22):
```sql
WITH bronze_data AS (
    SELECT *
    FROM iceberg_scan('s3://silver-bucket/iceberg/default/frankfurter_rates')
    WHERE source = 'frankfurter'
),
```

**How it works**:
1. DuckDB connects to MinIO S3 via `httpfs` extension
2. `iceberg_scan()` reads Iceberg metadata from PostgreSQL catalog
3. Parquet data files loaded into DuckDB memory
4. UNPIVOT transforms nested `rates__*` columns → rows
5. Deduplicate by latest `extraction_timestamp`

### Staging Models

#### stg_frankfurter (view)

**Input**: `iceberg_scan('s3://silver-bucket/iceberg/default/frankfurter_rates')`

**Transformation**:
```sql
-- UNPIVOT nested rates__* columns into rows
UNPIVOT bronze_data
ON COLUMNS('^rates__.*')
INTO
    NAME target_currency
    VALUE exchange_rate
```

**Output Schema**:
```sql
extraction_id        STRING          -- Unique per extraction
extraction_timestamp TIMESTAMP       -- ISO format
source              STRING           -- 'frankfurter'
source_tier         STRING           -- 'primary'
base_currency       STRING           -- 'EUR'
target_currency     STRING           -- ISO 4217 (e.g., 'USD', 'GBP')
exchange_rate       DOUBLE           -- Rate value (1 EUR = X target)
rate_date           DATE             -- Official ECB rate date
currency_pair       STRING           -- Derived: 'EUR/USD'
inverse_rate        DOUBLE           -- 1.0 / exchange_rate
dbt_loaded_at       TIMESTAMP        -- Transformation timestamp
```

**Deduplication**:
```sql
ROW_NUMBER() OVER (
    PARTITION BY base_currency, target_currency, rate_date
    ORDER BY extraction_timestamp DESC
) = 1  -- Keep only latest extraction per day
```

#### stg_exchangerate (view)
Same schema as `stg_frankfurter`, but:
- `source = 'exchangerate'`
- `base_currency = 'USD'`
- Input: `iceberg_scan('s3://silver-bucket/iceberg/default/exchangerate_rates')`

#### stg_currencylayer (view)
Same schema, but:
- `source = 'currencylayer'`
- `base_currency = 'USD'` (or 'EUR' for paid tier)
- Input: `iceberg_scan('s3://silver-bucket/iceberg/default/currencylayer_rates')`

---

## Validation Layer (Consensus Check)

### consensus_check (incremental table)

**Purpose**: Cross-validate rates from 3 sources, flag outliers

**Process**:
1. **Normalize** all rates to EUR base (convert USD→EUR using self-contained logic)
2. **Calculate Consensus**: `MEDIAN(rate)` across all sources per (rate_date, target_currency)
3. **Flag Deviations**: Any source >0.5% from median gets `status='FLAGGED'`

**Output Schema**:
```sql
rate_date            DATE
target_currency      STRING
currency_pair        STRING           -- 'EUR/{currency}'
consensus_rate       DOUBLE           -- Median rate across sources
source_count         INT              -- How many sources available (1-3)
source_breakdown     STRING           -- 'frankfurter:1.0850, exchangerate:1.0845'
frank_rate           DOUBLE           -- Frankfurter's rate (EUR-normalized)
exchangerate_rate    DOUBLE           -- ExchangeRate-API's rate (EUR-normalized)
currencylayer_rate   DOUBLE           -- CurrencyLayer's rate (EUR-normalized)
frank_dev            DOUBLE           -- % deviation from consensus
er_dev               DOUBLE
cl_dev               DOUBLE
status               STRING           -- 'FLAGGED' or 'OK'
dbt_loaded_at        TIMESTAMP
```

**Important**: This table **only contains FLAGGED rates**. Empty table = all validated ✅

**Example**:
```
Rate Date: 2026-01-28, Currency: USD

Frankfurter (EUR):  1.0850
ExchangeRate (USD): 1.0845 (normalized to EUR)
CurrencyLayer (USD): 1.0990 (outlier!)

Median: 1.0850
CurrencyLayer deviation: |1.0990 - 1.0850| / 1.0850 = 1.29% > 0.5%
Result: FLAGGED (status='FLAGGED')
```

---

## Silver Fact Layer

### fact_rates_validated (materialized table)

**Purpose**: Single source of truth for currency rates

**Input**: `stg_frankfurter` + `consensus_check`

**Filtering Logic**:
1. Uses **Frankfurter as primary source** (ECB institutional data)
2. **LEFT JOIN** with `consensus_check` on (target_currency, rate_date)
3. **Excludes flagged rates**: `WHERE validation_status = 'VALIDATED'`
4. Latest extraction per day (deduplication via ROW_NUMBER)

**Output Schema**:
```sql
extraction_id       STRING           -- Unique identifier
extraction_timestamp TIMESTAMP       -- When extracted
rate_date          DATE             -- Official rate date
currency_pair      STRING           -- 'EUR/USD'
base_currency      STRING           -- 'EUR' (always, Frankfurter source)
target_currency    STRING           -- ISO 4217 code
exchange_rate      DOUBLE           -- Validated rate
inverse_rate       DOUBLE           -- Reverse calculation
source             STRING           -- 'frankfurter'
source_tier        STRING           -- 'primary'
validation_status  STRING           -- 'VALIDATED' (only validated in this table)
severity           STRING           -- 'OK' (always, flagged excluded)
consensus_variance DOUBLE           -- % variance from consensus (0.0 if not flagged)
dbt_loaded_at      TIMESTAMP        -- Transformation timestamp
model_name         STRING           -- 'fact_rates_validated'
```

**Swiss Cheese Validation (4 Layers)**:
1. **Layer 1 (dlt)**: Schema validation, data types (Bronze ingestion)
2. **Layer 2 (dbt staging)**: Logical constraints (rate > 0, < 1M)
3. **Layer 3 (dbt consensus)**: Cross-source validation (>0.5% flagged)
4. **Layer 4 (dbt fact)**: Statistical checks (freshness <7 days, volume >=100 currencies)

---

## Gold Layer (Business Analytics - DuckDB)

### Storage Architecture

- **Query Pattern**: DuckDB reads Iceberg (via `iceberg_scan`), writes materialized tables locally
- **Storage**: `dbt_project/gold.duckdb` (local DuckDB file)
- **Why DuckDB**: Fast OLAP queries, embedded (no server), SQL interface
- **Materialization**: All gold models are `materialized='table'` (pre-computed for performance)

### Dimension Tables

#### dim_countries (table)

**Source**: Seed CSV (`dbt_project/seeds/country_currencies.csv`)

**Schema**:
```sql
country_code  STRING(2)    -- ISO 3166 (US, GB, FR, etc.)
country_name  STRING       -- Full name (United States, United Kingdom, etc.)
currency_code STRING(3)    -- ISO 4217 (USD, GBP, EUR, etc.)
region        STRING       -- Geographic region (Europe, Asia-Pacific, Americas)
```

**Sample Data**:
```
country_code | country_name       | currency_code | region
US           | United States      | USD           | Americas
GB           | United Kingdom     | GBP           | Europe
JP           | Japan              | JPY           | Asia-Pacific
```

---

### Fact Marts

#### mart_latest_rates (table)

**Purpose**: Latest validated rates enriched with country context

**Schema**:
```sql
rate_date           DATE
base_currency       STRING       -- 'EUR'
target_currency     STRING       -- ISO 4217
country_name        STRING       -- From dim_countries
region              STRING       -- From dim_countries
exchange_rate       DOUBLE       -- Validated rate
inverse_rate        DOUBLE       -- Reverse rate
consensus_variance  DOUBLE       -- Variance from consensus
validation_status   STRING       -- 'VALIDATED'
severity            STRING       -- 'OK'
```

**Use Case**: Dashboards showing "Latest EUR rates by region"

**Query Example**:
```sql
SELECT * FROM mart_latest_rates WHERE region = 'Europe';
```

---

#### mart_currency_conversions (table) **NEW**

**Purpose**: Pre-computed conversion matrix for top 10 currencies

**Schema**:
```sql
rate_date           DATE
from_currency       STRING       -- USD, EUR, GBP, etc. (10 currencies)
to_currency         STRING       -- USD, EUR, GBP, etc.
currency_pair       STRING       -- 'USD/GBP'
exchange_rate       DOUBLE       -- Cross rate (FROM → TO)
inverse_rate        DOUBLE       -- Reverse rate (TO → FROM)
dbt_loaded_at       TIMESTAMP
```

**Top 10 Currencies**: USD, EUR, GBP, JPY, AUD, CAD, CHF, CNY, HKD, SGD

**Cross Rate Calculation**:
```
1 EUR = 1.0850 USD  (eur_rate for USD)
1 EUR = 0.8612 GBP  (eur_rate for GBP)

USD/GBP = (1.0850 EUR/USD) / (0.8612 EUR/GBP) = 1.2599 USD/GBP
```

**Business Value**: Payment processing - convert 100 USD to GBP without manual calculation

**Query Example**:
```sql
SELECT * FROM mart_currency_conversions
WHERE from_currency = 'USD' AND to_currency = 'GBP';
-- Result: exchange_rate = 1.2599 (100 USD = 125.99 GBP)
```

---

#### mart_rate_volatility (table) **NEW**

**Purpose**: Risk assessment for FX exposure management

**Schema**:
```sql
rate_date           DATE
target_currency     STRING
exchange_rate       DOUBLE
daily_change_pct    DOUBLE       -- % change from yesterday
change_7d_pct       DOUBLE       -- % change over 7 days
change_30d_pct      DOUBLE       -- % change over 30 days
volatility_7d       DOUBLE       -- 7-day rolling stddev
volatility_30d      DOUBLE       -- 30-day rolling stddev
risk_level          STRING       -- 'STABLE', 'MEDIUM_RISK', 'HIGH_RISK'
dbt_loaded_at       TIMESTAMP
```

**Risk Thresholds**:
- **HIGH_RISK**: >2% daily change OR >5% weekly change
- **MEDIUM_RISK**: >1% daily change OR >3% weekly change
- **STABLE**: Otherwise

**History**: Keeps 90 days of data

**Business Value**: Finance team monitors GBP/TRY volatility, triggers hedging decisions

**Query Example**:
```sql
SELECT * FROM mart_rate_volatility
WHERE risk_level = 'HIGH_RISK'
ORDER BY ABS(daily_change_pct) DESC
LIMIT 10;
```

---

#### mart_data_quality_metrics (table) **NEW**

**Purpose**: Pipeline health SLA monitoring

**Schema**:
```sql
last_extraction      TIMESTAMP    -- Most recent extraction
last_rate_date       DATE         -- Most recent rate date
hours_since_extraction INT        -- Freshness metric
days_since_rate      INT          -- Staleness metric
currency_count       INT          -- How many currencies extracted
total_records        INT          -- Total rate records
validated_count      INT          -- Passed validation
ok_count             INT          -- Severity = OK
warning_count        INT          -- Severity = WARNING
ok_rate              DOUBLE       -- % validated (target: >90%)
flagged_count        INT          -- Consensus anomalies
avg_variance         DOUBLE       -- Average deviation
max_variance         DOUBLE       -- Worst deviation
pipeline_status      STRING       -- 'HEALTHY', 'WARNING', 'DEGRADED', 'STALE'
dbt_loaded_at        TIMESTAMP
```

**Health Rules**:
- **STALE**: No rates for >2 days
- **DEGRADED**: >5 flagged currencies
- **WARNING**: >10 warnings
- **HEALTHY**: Otherwise

**Single Row Table**: Always exactly 1 row (current status)

**Business Value**: SLA monitoring, alerts if data >2 days old

**Query Example**:
```sql
SELECT * FROM mart_data_quality_metrics;
-- Expected: pipeline_status = 'HEALTHY', ok_rate >= 0.90
```

---

#### mart_monthly_summary (table) **NEW**

**Purpose**: Pre-aggregated monthly rates for financial reporting

**Schema**:
```sql
month               DATE         -- First day of month (2026-01-01)
year                INT          -- 2026
month_num           INT          -- 1-12
target_currency     STRING       -- ISO 4217
sample_count        INT          -- Number of daily rates in month
min_rate            DOUBLE       -- Minimum rate in month
max_rate            DOUBLE       -- Maximum rate in month
avg_rate            DOUBLE       -- Average rate
median_rate         DOUBLE       -- Median rate
stddev_rate         DOUBLE       -- Standard deviation
volatility_pct      DOUBLE       -- (max - min) / avg * 100
opening_rate        DOUBLE       -- First rate of month
closing_rate        DOUBLE       -- Last rate of month
dbt_loaded_at       TIMESTAMP
```

**History**: 24 months (2 years)

**Business Value**: Monthly board reports, YoY comparisons

**Query Example**:
```sql
SELECT * FROM mart_monthly_summary
WHERE year = 2026 AND month_num = 1
ORDER BY target_currency;
```

---

## Field Lineage Example (EUR/USD)

### Bronze → Silver → Gold

**Bronze** (`frankfurter_rates` JSONL):
```json
{
  "rates": {"USD": 1.0850}
}
```
↓ dlt flattens to `rates__USD = 1.0850`

**Silver Iceberg** (Parquet on S3):
```
rates__USD = 1.0850
base_currency = 'EUR'
rate_date = '2026-01-28'
source = 'frankfurter'
```

**dbt Staging** (`stg_frankfurter` view):
```sql
-- UNPIVOT rates__USD → target_currency='USD', exchange_rate=1.0850
base_currency: 'EUR'
target_currency: 'USD'         -- From UNPIVOT
exchange_rate: 1.0850          -- From UNPIVOT
currency_pair: 'EUR/USD'       -- CONCAT(base, '/', target)
inverse_rate: 0.9217           -- 1.0 / 1.0850
```

**Validation** (`consensus_check`):
```sql
target_currency: 'USD'
consensus_rate: 1.0850         -- MEDIAN(frank: 1.0850, er: 1.0845)
frank_rate: 1.0850
frank_dev: 0.0000              -- |1.0850 - 1.0850| / 1.0850
status: 'OK'                   -- <0.5% deviation
```

**Fact** (`fact_rates_validated` table):
```sql
currency_pair: 'EUR/USD'
exchange_rate: 1.0850
validation_status: 'VALIDATED' -- Passed consensus check
consensus_variance: 0.0000
severity: 'OK'
```

**Gold Marts**:
- `mart_latest_rates`: 1.0850 + country_name: "United States"
- `mart_currency_conversions`: USD→GBP = (1.0850 EUR/USD) / (0.8612 EUR/GBP) = 1.2599
- `mart_rate_volatility`: daily_change_pct, volatility_7d calculations

---

## Validation Rules Summary

| Layer | Validation | Tool | Example |
|-------|-----------|------|---------|
| Bronze | None (ELT) | - | Store raw even if invalid |
| Silver Staging | Logical constraints | dbt tests | exchange_rate > 0, < 1B |
| Silver Consensus | Cross-source | dbt logic | Flag >0.5% variance |
| Silver Fact | Statistical | dbt tests | Recency (<7 days), volume (>=100 currencies) |
| Gold Marts | Business rules | dbt tests | ok_rate >= 90%, risk_level IN ('STABLE'...) |

---

## dbt Commands Reference

**Run entire pipeline**:
```bash
dbt run                        # All models
dbt run --select silver.*     # Only silver layer
dbt run --select gold.*       # Only gold layer
```

**Run specific model**:
```bash
dbt run --select fact_rates_validated
dbt run --select mart_currency_conversions+  # Model + downstream
```

**Test data quality**:
```bash
dbt test                       # All tests
dbt test --select silver.*    # Silver layer tests
dbt test --select gold.*      # Gold layer tests
```

**Generate documentation**:
```bash
dbt docs generate
dbt docs serve                 # http://localhost:8080
```

---

## Quick Decision Tree

**"Which layer should I query?"**
- **Bronze**: Never (raw API responses, use for audit only)
- **Silver Iceberg**: Debugging dbt staging models
- **Silver Fact** (`fact_rates_validated`): Downstream services (DynamoDB sync, APIs)
- **Gold Marts**: Everything else (analytics, dashboards, reports)

**"Which source to trust?"**
- **Primary**: Frankfurter (ECB institutional data, used in fact table)
- **Validation**: ExchangeRate-API + CurrencyLayer (consensus check)
- **Failover**: CurrencyLayer (if others unavailable)

**"How to detect bad data?"**
1. Check `consensus_check` for flagged rates
2. Check `mart_data_quality_metrics` for pipeline health
3. Run `dbt test` for schema violations

**"How to query Iceberg directly?"**
```sql
-- Connect to DuckDB
duckdb dbt_project/gold.duckdb

-- Load Iceberg extension (if not auto-loaded)
LOAD iceberg;

-- Query Iceberg table
SELECT * FROM iceberg_scan('s3://silver-bucket/iceberg/default/frankfurter_rates') LIMIT 10;
```

---

## PostgreSQL Star Schema (Future)

**Note**: Designed in `schema/star_schema.sql` but **not yet implemented**. DuckDB is current implementation.

**If implemented**, would add:
- Surrogate keys (dim_currency.currency_key instead of currency_code)
- Partitioned fact tables (monthly partitions on fact_rates_history)
- Materialized views (vw_rates_latest, vw_rates_daily_agg)
- SCD Type 2 tracking (valid_from, valid_to columns)

**When to implement**: If DuckDB becomes bottleneck (>10M rows) or need multi-user ACID transactions.

---

## Summary

**Data Flow**:
```
APIs → Bronze (JSONL) → Iceberg Compaction → Silver (Iceberg) → dbt (DuckDB) → Gold (Tables)
```

**Key Technologies**:
- **dlt**: Schema tracking, state management, Bronze ingestion
- **Apache Iceberg**: ACID tables, time travel, Parquet compression
- **DuckDB**: OLAP analytics, embedded database, iceberg_scan()
- **dbt**: SQL-based transformations, data quality tests
- **PostgreSQL**: Iceberg catalog metadata storage

**Total Models**:
- Silver: 3 staging views + 1 validation table + 1 fact table = 5
- Gold: 1 dimension + 6 marts = 7
- **Total**: 12 dbt models
