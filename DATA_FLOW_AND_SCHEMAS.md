# 📊 Data Flow Summary

1. **Audit Layer (RAW)** (dlt → JSONL): Raw API responses with metadata, stored in MinIO
2. **Truth Layer** (Iceberg): Compacted, deduplicated, MAP reconstructed from flattened schema
3. **Analytics Layer - Staging** (dbt): UNNEST MAP to rows, add calculated fields
4. **Analytics Layer - Validation** (dbt): Multi-source consensus check, COALESCE with source priority
5. **Analytics Layer - Analytics** (dbt): Marts with aggregations, volatility, country metadata
6. **Hot Tier** (DynamoDB): Latest validated rates with country/region metadata for downstream services

---

## Audit Layer Schema with [dlt (data load tool)](https://dlthub.com/)
> Schema evolution and metadata tracking guaranteed by dlt

**Storage**: MinIO S3 buckets configured via `ENV` variables (you can set them also via `.dlt/secrets.toml`)
**Format**: JSONL (JSON Lines) - one record per extraction
**Lifecycle**: Append-only, never deleted (audit trail and reprocessability)
**Extractors**: `src/frankfurter_extractor.py`, `src/exchangerate_extractor.py`, `src/currencylayer_extractor.py`

### Example Raw Schemas
#### Frankfurter RAW 

**Schema** (as stored by dlt):
```json
{
  "extraction_id": "fr_2024-02-03_USD_1706965200",
  "extraction_timestamp": "2024-02-03T14:30:22.123456",
  "source": "frankfurter",
  "source_tier": "primary",
  "base_currency": "USD",
  "rate_date": "2024-02-03",
  "rates": {
    "EUR": 0.9234,
    "GBP": 0.7891,
    "JPY": 149.23,
    "AED": 3.6725,
    ... // ~30 currencies
  },
  "api_response_raw": {...},
  "http_status_code": 200,
  "response_size_bytes": 2048
}
```

**Important Notes**:
- dlt **flattens** the `rates` MAP into columns: `rates__EUR`, `rates__GBP`, `rates__JPY`, etc.
- This flattening is reversed in Silver layer (Iceberg loader reconstructs MAP)
- Rate values are cast to `float(v)` to prevent DuckDB type-versioned column issues

#### ExchangeRate-API raw
**API**: ExchangeRate-API (Free v4 or v6 with key)


**Schema** (as stored by dlt):
```json
{
  "extraction_id": "exchangerate_20240203_143025",
  "extraction_timestamp": "2024-02-03T14:30:25.123456",
  "source": "exchangerate",
  "source_tier": "secondary",
  "base_currency": "USD",
  "rate_date": "2024-02-03",
  "rates": {
    "EUR": 0.9235,
    "GBP": 0.7892,
    "JPY": 149.25,
    ... // ~160 currencies
  },
  "api_response_raw": {...},
  "http_status_code": 200
}
```

**Critical Transformations**:
- Strips prefix from rates: `rates__USD` → `USD` (dlt normalization artifact)
- Explicitly casts all values to FLOAT for type consistency

### CurrencyLayer Raw (Tertiary Source)

**API**: CurrencyLayer (Paid/Professional tier)
**Modes**: Daily (`/live`) + Historical (`/timeframe`)


**Schema** (as stored by dlt):
```json
{
  "extraction_id": "currencylayer_2024-02-03_1706965228",
  "extraction_timestamp": "2024-02-03T14:30:28.123456",
  "source": "currencylayer",
  "source_tier": "secondary",
  "base_currency": "USD",
  "rate_date": "2024-02-03",
  "rates": {
    "EUR": 0.9233,
    "GBP": 0.7890,
    "JPY": 149.20,
    ... // ~170 currencies
  },
  "api_response_raw": {...},
  "http_status_code": 200
}
```

**Critical Alterations**:
- API returns quotes as `USDGBP`, `USDEUR` → stripped to `GBP`, `EUR`
- Error code 104 (quota exhausted) detection in response body
- DOUBLE-cast all values to prevent type issues

### Unified Audit Layer Schema

All three sources produce this structure after dlt processing:

| Column | Type | Description |
|--------|------|-------------|
| `extraction_id` | VARCHAR | Unique identifier: `{source}_{date}_{timestamp}` |
| `extraction_timestamp` | TIMESTAMP | When data was extracted (ISO 8601) |
| `source` | VARCHAR | `frankfurter`, `exchangerate`, or `currencylayer` |
| `source_tier` | VARCHAR | `primary`, `secondary`, or `tertiary` |
| `base_currency` | VARCHAR | Base currency (USD or EUR, normalized to USD later) |
| `rate_date` | DATE | Official rate date from API |
| `rates` | MAP<VARCHAR, DOUBLE> | **In-memory**: {currency → rate}<br/>**On-disk (dlt)**: Flattened to `rates__EUR`, `rates__GBP`, etc. |
| `api_response_raw` | JSON | Complete API response for audit |
| `http_status_code` | INT | HTTP response code (200 = success, 429 = rate limited) |
| `response_size_bytes` | INT | Response size (optional) |

---

## Silver Layer Schema (Apache Iceberg)

**Storage**: MinIO S3 buckets (configured via `pyiceberg_catalog.db`)
**Format**: Apache Iceberg + Parquet (columnar)
**Catalog**: SQLite catalog at `/data/pyiceberg_catalog.db`
**Loader**: `src/iceberg_loader.py` (DuckDB → PyIceberg)
**Tables**: `default_namespace.frankfurter_rates`, `default_namespace.exchangerate_rates`, `default_namespace.currencylayer_rates`

### Scope

Compact Bronze JSONL files into queryable, deduplicated Iceberg tables with:
- **MAP Reconstruction**: Rebuilds `rates: MAP<VARCHAR, DOUBLE>` from flattened dlt columns
- **Deduplication**: Latest extraction per `(rate_date, source, base_currency)`
- **Idempotent Upserts**: Delete+Append strategy (avoids PyIceberg MAP merge bug)
- **Data Quality Checks**: NULL rate detection, MAP key validation
- **Schema Evolution**: Automatic column additions

### Transformation Logic (iceberg_loader.py)

**Input**: JSONL files from Bronze with flattened schema (`rates__USD`, `rates__GBP`, etc.)

### Output Schema (Iceberg Tables)

All three tables (`frankfurter_rates`, `exchangerate_rates`, `currencylayer_rates`) follow this schema:

| Column | Type | Description |
|--------|------|-------------|
| `extraction_id` | VARCHAR | Unique extraction identifier |
| `extraction_timestamp` | TIMESTAMP | When data was extracted |
| `source` | VARCHAR | `frankfurter`, `exchangerate`, or `currencylayer` |
| `source_tier` | VARCHAR | `primary`, `secondary`, or `tertiary` |
| `base_currency` | VARCHAR | Base currency (USD or EUR) |
| `rate_date` | DATE | Official rate date |
| `rates` | **MAP<VARCHAR, DOUBLE>** | **Reconstructed**: {currency → rate} |
| `http_status_code` | INT | HTTP response code |

**Primary Keys**: `(rate_date, source, base_currency)` - enforced via delete+append



## Analytics Layer Schema (dbt + DuckDB)

**Storage**: Persistent DuckDB database volume-shared file (`/data/analytics.duckdb`)
**Technology**: dbt (data build tool) with DuckDB adapter
**Location**: `dbt_project/models/`
**Materialization**: Incremental with MERGE strategy (upsert behavior)

### Architecture: 3-Tier Analytics Layer

1. **Staging** (`models/staging/`): UNNEST MAP, clean data, add calculated fields
2. **Consensus Validation** (`models/validation/`): Consensus checks, COALESCE with source priority
3. **Analytics Marts** (`models/analytics/`): conversion-rate tables, historical timeseries, aggregation stats, health tables, etc.

---

### Output Schema (Staging Models)

| Column | Type | Description |
|--------|------|-------------|
| `extraction_id` | VARCHAR | Unique extraction identifier |
| `extraction_timestamp` | TIMESTAMP | When data was extracted |
| `source` | VARCHAR | `frankfurter`, `exchangerate`, or `currencylayer` |
| `source_tier` | VARCHAR | `primary`, `secondary`, or `tertiary` |
| `base_currency` | VARCHAR | Base currency (USD or EUR) |
| `target_currency` | VARCHAR | Target currency (GBP, JPY, EUR, etc.) |
| `exchange_rate` | DOUBLE | Exchange rate value |
| `rate_date` | DATE | Official rate date |
| `currency_pair` | VARCHAR | Format: `"USD/GBP"` |
| `inverse_rate` | DOUBLE | `1.0 / exchange_rate` (for reverse conversions) |
| `dbt_loaded_at` | TIMESTAMP | dbt processing timestamp |

**Materialization**: Incremental (unique_key: `[base_currency, target_currency, rate_date]`)

**Incremental Logic**:
- Daily mode: Only process `rate_date > MAX(rate_date)` from existing table
- Backfill mode: Process specified date range (allows out-of-order backfills)

---
## Gold Layer - Validation Models

### Consensus cross-validated fact table

### fact_rates_validated

**Output Schema** (Single Source of Truth):

| Column | Type | Description |
|--------|------|-------------|
| `extraction_id` | VARCHAR | Source extraction ID (lineage) |
| `extraction_timestamp` | TIMESTAMP | Source extraction timestamp (lineage) |
| `rate_date` | DATE | Rate date |
| `currency_pair` | VARCHAR | `"USD/XXX"` |
| `base_currency` | VARCHAR | Base currency (USD or EUR) |
| `target_currency` | VARCHAR | Target currency |
| `exchange_rate` | DOUBLE | **Validated** exchange rate |
| `inverse_rate` | DOUBLE | `1.0 / exchange_rate` |
| `source` | VARCHAR | **Actual source used** (frankfurter/exchangerate/currencylayer) |
| `source_tier` | VARCHAR | **Actual tier** (primary/secondary/tertiary) |
| `validation_status` | VARCHAR | Always `'VALIDATED'` (flagged rates excluded) |
| `severity` | VARCHAR | Always `'OK'` (anomalies excluded) |
| `consensus_variance` | DOUBLE | Variance from consensus (0.0 for non-flagged) |
| `dbt_loaded_at` | TIMESTAMP | dbt processing timestamp |
| `model_name` | VARCHAR | Always `'fact_rates_validated'` |

**Materialization**: Incremental (unique_key: `[rate_date, target_currency, base_currency]`)

**Incremental Logic**: 3-day lookback for late-arriving data
```sql
WHERE rate_date >= (SELECT MAX(rate_date) FROM {{ this }}) - INTERVAL '3 days'
```