# Architecture Design: ETL vs ELT Approach

## Executive Decision: ELT (Extract, Load, Transform)

### Strategic Rationale
After evaluating both approaches, **ELT is the recommended architecture** for the Make.com currency rate pipeline based on:

1. **Audit Trail Priority:** Financial data requires complete audit trails
2. **Data Lineage:** Must trace every rate to its original source API response
3. **Reprocessing Capability:** Business logic may change; raw data enables reprocessing
4. **Storage Cost:** Modern cloud storage makes raw data retention cost-effective
5. **Regulatory Compliance:** ECB data requires preservation of original responses

---

## ELT vs ETL Comparison

| Dimension | ETL (Transform First) | ELT (Load Raw First) | Winner |
|-----------|----------------------|---------------------|--------|
| **Audit Trail** | Loses raw source data | Preserves complete API responses | **ELT** ✓ |
| **Data Lineage** | Difficult to trace back | Full traceability to source | **ELT** ✓ |
| **Reprocessing** | Must re-fetch from API (cost) | Reprocess from warehouse (free) | **ELT** ✓ |
| **Schema Changes** | Pipeline breaks immediately | Raw layer unaffected | **ELT** ✓ |
| **Storage Cost** | Minimal (transformed only) | Higher (raw + transformed) | ETL ✓ |
| **Processing Speed** | Faster (transform once) | Slower (transform in warehouse) | ETL ✓ |
| **Debugging** | No raw data to inspect | Can inspect original responses | **ELT** ✓ |
| **Regulatory Compliance** | Risk of data loss | Complete evidence chain | **ELT** ✓ |

**Score: ELT 6 | ETL 2**

---

## Architecture: Three-Layer Medallion Pattern

### Layer 1: Bronze (Raw Evidence)
**Purpose:** Immutable storage of original API responses

**Schema:**
```
bronze_currency_rates
├── extraction_id (UUID, PK)
├── source_name (VARCHAR) -- 'exchangerate-api', 'frankfurter-ecb', 'fixer'
├── extraction_timestamp (TIMESTAMP)
├── http_status_code (INT)
├── raw_response (JSON/JSONB)
├── request_url (TEXT)
├── request_params (JSON)
└── extraction_method (VARCHAR) -- 'scheduled', 'on-demand', 'failover'
```

**Characteristics:**
- **Append-Only:** Never update or delete
- **Complete Capture:** Store entire HTTP response including headers
- **Metadata Rich:** Capture extraction context
- **Long Retention:** 7 years for audit compliance

**Example Record:**
```json
{
  "extraction_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "source_name": "exchangerate-api",
  "extraction_timestamp": "2026-01-24T14:30:00Z",
  "http_status_code": 200,
  "raw_response": {
    "result": "success",
    "time_last_update_unix": 1706104800,
    "time_next_update_unix": 1706191200,
    "base_code": "USD",
    "conversion_rates": {
      "EUR": 0.9234,
      "GBP": 0.7912,
      "JPY": 149.32
    }
  },
  "request_url": "https://v6.exchangerate-api.com/v6/{API_KEY}/latest/USD",
  "request_params": {"base": "USD"},
  "extraction_method": "scheduled"
}
```

---

### Layer 2: Silver (Normalized & Validated)
**Purpose:** Cleaned, validated, and standardized rates

**Schema:**
```
silver_currency_rates
├── rate_id (UUID, PK)
├── extraction_id (UUID, FK to bronze)
├── source_name (VARCHAR)
├── base_currency (CHAR(3))
├── target_currency (CHAR(3))
├── exchange_rate (DECIMAL(20,10))
├── valid_from (TIMESTAMP)
├── valid_to (TIMESTAMP) -- NULL for current rate
├── extraction_timestamp (TIMESTAMP)
├── validation_status (VARCHAR) -- 'passed', 'failed', 'warning'
├── validation_flags (JSON) -- Details of validation checks
└── is_current (BOOLEAN)
```

**Transformation Logic:**
1. **Unpivot:** Convert JSON rates object into individual currency pairs
2. **Validate:** Apply three-layer validation (schema, zero-check, Z-score)
3. **Standardize:** Ensure ISO 4217 currency codes
4. **Enrich:** Add temporal validity windows
5. **Flag:** Mark current vs historical rates

**Validation Flags:**
```json
{
  "schema_valid": true,
  "rate_positive": true,
  "z_score": 0.34,
  "z_score_threshold": 3.0,
  "volatility_check": "passed",
  "cross_validation_ecb": 0.0012,
  "cross_validation_status": "within_tolerance"
}
```

**SCD Type 2 Implementation:**
- When new rate arrives, set `valid_to` of current rate to new rate's `valid_from`
- Insert new rate with `valid_to = NULL`
- Enables "time-travel" queries for historical analysis

---

### Layer 3: Gold (Business-Ready)
**Purpose:** Optimized for consumption by Make.com and analytics

**Schema 1: DIM_CURRENCY (Dimension Table)**
```
dim_currency
├── currency_code (CHAR(3), PK)
├── currency_name (VARCHAR)
├── currency_symbol (VARCHAR)
├── decimal_places (INT)
├── is_crypto (BOOLEAN)
└── region (VARCHAR)
```

**Schema 2: FACT_CURRENCY_RATE (Fact Table)**
```
fact_currency_rate
├── rate_key (INT, PK, Auto-increment)
├── from_currency_key (FK to dim_currency)
├── to_currency_key (FK to dim_currency)
├── exchange_rate (DECIMAL(20,10))
├── inverse_rate (DECIMAL(20,10)) -- Pre-calculated for performance
├── rate_date (DATE)
├── rate_timestamp (TIMESTAMP)
├── source_tier (VARCHAR) -- 'institutional', 'regulatory', 'commercial'
├── valid_from (TIMESTAMP)
├── valid_to (TIMESTAMP)
└── mid_rate (DECIMAL(20,10)) -- Average of bid/ask if available
```

**Schema 3: VW_LATEST_RATES (View for Make.com)**
```sql
CREATE VIEW vw_latest_rates AS
SELECT
  base_currency,
  target_currency,
  exchange_rate,
  inverse_rate,
  extraction_timestamp,
  source_name
FROM fact_currency_rate
WHERE valid_to IS NULL
  AND validation_status = 'passed';
```

**Optimizations:**
- **Materialized View:** Refresh every 5 minutes for fast Make.com access
- **Indexes:** Composite indexes on (base_currency, target_currency, valid_from)
- **Partitioning:** Partition by rate_date for historical query performance
- **Caching:** Redis cache for top 20 currency pairs (95% of traffic)

---

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     EXTRACTION LAYER                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │ ExchangeRate │   │ Frankfurter  │   │   Fixer.io   │        │
│  │     API      │   │     (ECB)    │   │  (Optional)  │        │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘        │
│         │                  │                   │                 │
│         └──────────────────┼───────────────────┘                 │
│                            ▼                                     │
│                   ┌────────────────┐                             │
│                   │  Python ETL    │                             │
│                   │  (Extraction)  │                             │
│                   └────────┬───────┘                             │
│                            │                                     │
└────────────────────────────┼─────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     BRONZE LAYER (RAW)                           │
├─────────────────────────────────────────────────────────────────┤
│  bronze_currency_rates                                           │
│  • Immutable append-only                                         │
│  • Complete API responses (JSON)                                 │
│  • 7-year retention for audit                                    │
└────────────────────────────┬─────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                 TRANSFORMATION LAYER (dbt/SQL)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │   Unpivot    │   │  Validation  │   │ Enrichment   │        │
│  │   Rates      │──▶│  • Schema    │──▶│ • SCD Type 2 │        │
│  │              │   │  • Zero Chk  │   │ • Timestamps │        │
│  └──────────────┘   │  • Z-Score   │   └──────────────┘        │
│                     └──────────────┘                             │
│                                                                  │
└────────────────────────────┬─────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SILVER LAYER (VALIDATED)                       │
├─────────────────────────────────────────────────────────────────┤
│  silver_currency_rates                                           │
│  • Validated & normalized                                        │
│  • SCD Type 2 for time-travel                                    │
│  • 2-year retention                                              │
└────────────────────────────┬─────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              TRANSFORMATION LAYER (Business Logic)               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │ Dimension    │   │ Fact Table   │   │ Aggregations │        │
│  │ Building     │──▶│ Building     │──▶│ & Views      │        │
│  │              │   │              │   │              │        │
│  └──────────────┘   └──────────────┘   └──────────────┘        │
│                                                                  │
└────────────────────────────┬─────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    GOLD LAYER (BUSINESS-READY)                   │
├─────────────────────────────────────────────────────────────────┤
│  dim_currency + fact_currency_rate + vw_latest_rates            │
│  • Optimized for consumption                                     │
│  • Materialized views                                            │
│  • 1-year retention (fact), permanent (dim)                      │
└────────────────────────────┬─────────────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
┌──────────────────────┐      ┌──────────────────────┐
│     Make.com         │      │     Analytics        │
│  • Workflows         │      │  • BI Dashboards     │
│  • Automations       │      │  • Celonis           │
│  • Webhooks          │      │  • Ad-hoc Queries    │
└──────────────────────┘      └──────────────────────┘
```

---

## Processing Paradigm: Hybrid Batch + Event-Driven

### Batch Processing (Primary Path)
**Schedule:** Every 4 hours (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)

**Orchestration:** Apache Airflow

**DAG Structure:**
```python
# Pseudo-DAG
extract_exchangerate_api >> load_bronze_primary
extract_frankfurter_ecb >> load_bronze_fallback
load_bronze_primary >> transform_silver >> validate_silver >> build_gold
validate_silver >> cross_validate_sources
cross_validate_sources >> alert_on_deviation
build_gold >> refresh_materialized_views
refresh_materialized_views >> trigger_make_webhook
```

**Why Batch?**
- **Cost Optimization:** 6 extractions/day vs 1,440 (per-minute)
- **Consistency:** All downstream systems see same data at same time
- **Audit Simplicity:** Clear extraction boundaries
- **ECB Alignment:** ECB publishes once daily at 16:00 CET

---

### Event-Driven Processing (Operational Path)
**Trigger:** Volatility Alert (>2% change in major pairs)

**Flow:**
1. **Detection:** Batch process compares current vs previous rates
2. **Threshold Check:** If USD/EUR, USD/GBP, or USD/JPY moves >2%
3. **Webhook Trigger:** POST to Make.com webhook with alert payload
4. **Make.com Action:**
   - Send Slack notification to Finance team
   - Update e-commerce price buffers
   - Log alert in audit trail

**Why Event-Driven for Alerts Only?**
- **High Value:** Only trigger actions on significant changes
- **Low Volume:** <5% of extractions trigger alerts
- **Real-time Where It Matters:** Operational actions need instant response

---

## Technology Stack

### Extraction Layer
**Language:** Python 3.11+
**Framework:** `requests` + custom retry logic
**Orchestration:** Apache Airflow

**Key Libraries:**
- `requests`: HTTP client
- `tenacity`: Retry with exponential backoff
- `pydantic`: API response validation
- `structlog`: Structured logging

---

### Storage Layer
**Primary Database:** PostgreSQL 15+ (with JSONB support)
**Why PostgreSQL?**
- Native JSONB for bronze layer
- Excellent indexing for time-series queries
- SCD Type 2 support with temporal queries
- Wide Make.com connector support

**Alternative (Cloud):** Snowflake or BigQuery for scale

**Caching Layer:** Redis 7+
- Cache top 20 currency pairs (TTL: 5 minutes)
- Reduce database load by 95%

---

### Transformation Layer
**Primary Tool:** dbt (data build tool)
**Why dbt?**
- SQL-based transformations (team familiarity)
- Built-in testing framework
- Automatic data lineage documentation
- Version control for transformations

**Alternative:** Plain SQL for simpler deployments

---

### Orchestration Layer
**Tool:** Apache Airflow 2.8+
**Why Airflow?**
- Industry standard for data pipelines
- Rich retry/alerting capabilities
- DAG versioning with Git
- Extensive operator library

**Alternative:** Prefect or Dagster for modern approach

---

### Observability
**Logging:** Structured logs (JSON) via `structlog`
**Metrics:** Prometheus + Grafana
**Alerting:** PagerDuty for critical failures
**Data Quality:** Great Expectations or dbt tests

**Key Metrics to Monitor:**
- API response time (p50, p95, p99)
- API success rate
- Extraction-to-load latency
- Validation failure rate
- Z-score violations
- Cross-validation deviation

---

## Deployment Architecture

### Containerization
**Platform:** Docker
**Base Image:** `python:3.11-slim`

**Why Docker?**
- Environment parity (dev/staging/prod)
- Portability across cloud providers
- Easy CI/CD integration
- Resource isolation

**Container Structure:**
```
currency-rate-pipeline/
├── Dockerfile
├── docker-compose.yml (local dev)
├── requirements.txt
└── src/
```

---

### Orchestration Platform
**Option 1 (Self-Hosted):** Kubernetes + Airflow
**Option 2 (Managed):** AWS MWAA (Managed Airflow) or Google Cloud Composer

**Why Managed Airflow?**
- Reduced operational overhead
- Auto-scaling DAG workers
- Built-in monitoring
- SLA guarantees

---

### CI/CD Pipeline
**Platform:** GitHub Actions or GitLab CI

**Workflow:**
1. **Code Push** → Trigger CI
2. **Run Tests** → Unit + integration tests
3. **Build Docker Image** → Tag with commit SHA
4. **Push to Registry** → ECR/GCR/Docker Hub
5. **Deploy to Staging** → Run smoke tests
6. **Manual Approval** → Senior engineer approval
7. **Deploy to Production** → Blue-green deployment

---

## Failover & Resilience Implementation

### Circuit Breaker Pattern

**State Machine:**
```
CLOSED (normal operation)
  ↓ (5 consecutive failures)
OPEN (reject all requests, use fallback)
  ↓ (after 60 seconds)
HALF-OPEN (try one request)
  ├─ Success → CLOSED
  └─ Failure → OPEN
```

**Implementation:**
```python
# Pseudo-code
if circuit_breaker.is_open():
    logger.warning("Primary source circuit open, using fallback")
    return extract_from_fallback_source()
else:
    try:
        result = extract_from_primary_source()
        circuit_breaker.record_success()
        return result
    except APIError as e:
        circuit_breaker.record_failure()
        raise
```

---

### Data Validation Layers

**Layer 1: Schema Validation**
```python
# Pydantic model
class ExchangeRateResponse(BaseModel):
    result: str
    base_code: str
    conversion_rates: Dict[str, float]
    time_last_update_unix: int
```

**Layer 2: Business Rules Validation**
- All rates must be > 0
- Currency codes must be ISO 4217 valid
- Timestamp must be within last 48 hours

**Layer 3: Statistical Validation (Z-Score)**
```python
z_score = (current_rate - mean_24h) / std_dev_24h
if abs(z_score) > 3.0:
    alert("Potential data quality issue: Z-score = {z_score}")
    circuit_breaker.trip()
```

---

## Storage Strategy (Theoretical Implementation)

### Database Selection: PostgreSQL

**Justification:**
- **JSONB Support:** Efficient storage/querying of bronze layer JSON
- **Temporal Queries:** Native support for SCD Type 2 patterns
- **Indexing:** GIN indexes on JSONB, BRIN indexes on timestamps
- **Partitioning:** Table partitioning by date for performance
- **Ecosystem:** Wide support in dbt, Airflow, Make.com

**Schema DDL:**
```sql
-- Bronze Layer
CREATE TABLE bronze_currency_rates (
  extraction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_name VARCHAR(50) NOT NULL,
  extraction_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  http_status_code INT,
  raw_response JSONB NOT NULL,
  request_url TEXT,
  request_params JSONB,
  extraction_method VARCHAR(20)
);

CREATE INDEX idx_bronze_timestamp ON bronze_currency_rates(extraction_timestamp DESC);
CREATE INDEX idx_bronze_source ON bronze_currency_rates(source_name, extraction_timestamp DESC);
CREATE INDEX idx_bronze_response_gin ON bronze_currency_rates USING GIN(raw_response);

-- Silver Layer
CREATE TABLE silver_currency_rates (
  rate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  extraction_id UUID REFERENCES bronze_currency_rates(extraction_id),
  source_name VARCHAR(50) NOT NULL,
  base_currency CHAR(3) NOT NULL,
  target_currency CHAR(3) NOT NULL,
  exchange_rate DECIMAL(20,10) NOT NULL CHECK (exchange_rate > 0),
  valid_from TIMESTAMPTZ NOT NULL,
  valid_to TIMESTAMPTZ,
  extraction_timestamp TIMESTAMPTZ NOT NULL,
  validation_status VARCHAR(20) NOT NULL,
  validation_flags JSONB,
  is_current BOOLEAN GENERATED ALWAYS AS (valid_to IS NULL) STORED
);

CREATE INDEX idx_silver_current ON silver_currency_rates(base_currency, target_currency, valid_from DESC)
WHERE is_current = TRUE;
CREATE INDEX idx_silver_temporal ON silver_currency_rates(base_currency, target_currency, valid_from, valid_to);

-- Gold Layer
CREATE TABLE fact_currency_rate (
  rate_key SERIAL PRIMARY KEY,
  from_currency CHAR(3) NOT NULL,
  to_currency CHAR(3) NOT NULL,
  exchange_rate DECIMAL(20,10) NOT NULL,
  inverse_rate DECIMAL(20,10) NOT NULL,
  rate_date DATE NOT NULL,
  rate_timestamp TIMESTAMPTZ NOT NULL,
  source_tier VARCHAR(20),
  valid_from TIMESTAMPTZ NOT NULL,
  valid_to TIMESTAMPTZ
) PARTITION BY RANGE (rate_date);

CREATE INDEX idx_gold_latest ON fact_currency_rate(from_currency, to_currency, rate_timestamp DESC)
WHERE valid_to IS NULL;
```

**Partitioning Strategy:**
- Bronze: Partitioned monthly (for archival)
- Silver: Partitioned quarterly (active queries)
- Gold: Partitioned monthly (performance)

**Retention Policy:**
- Bronze: 7 years (audit compliance)
- Silver: 2 years (active analysis)
- Gold: 1 year hot, 7 years cold storage

---

## Alternative: Cloud-Native Storage

### Snowflake Implementation
**Advantages:**
- Automatic scaling
- Separation of storage/compute
- Native JSON support
- Time-travel built-in

**Schema Pattern:**
```sql
-- Bronze (Variant type for JSON)
CREATE TABLE bronze_currency_rates (
  extraction_id VARCHAR PRIMARY KEY,
  raw_response VARIANT,
  extraction_timestamp TIMESTAMP_NTZ,
  source_name VARCHAR
);

-- Silver (flatten with LATERAL FLATTEN)
CREATE TABLE silver_currency_rates AS
SELECT
  bronze.extraction_id,
  bronze.source_name,
  bronze.extraction_timestamp,
  f.key::STRING AS target_currency,
  bronze.raw_response:base_code::STRING AS base_currency,
  f.value::FLOAT AS exchange_rate
FROM bronze_currency_rates bronze,
LATERAL FLATTEN(input => bronze.raw_response:conversion_rates) f;
```

---

## Decision Summary: ELT with Three-Layer Medallion

| Layer | Purpose | Technology | Retention |
|-------|---------|------------|-----------|
| **Bronze** | Raw audit trail | JSONB / Variant | 7 years |
| **Silver** | Validated, normalized | Structured tables (SCD2) | 2 years |
| **Gold** | Business-ready | Star schema + views | 1 year hot |

**Key Benefits:**
1. Complete audit trail from source to consumption
2. Reprocess transformations without API costs
3. Schema flexibility (bronze absorbs API changes)
4. Time-travel analysis for historical accuracy
5. Data lineage automatically documented

This architecture aligns with enterprise governance requirements while maintaining pragmatic simplicity for a POC-to-production evolution.
