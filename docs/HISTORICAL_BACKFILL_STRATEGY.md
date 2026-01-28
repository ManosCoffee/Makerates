# Historical Backfill Strategy

## Problem Statement

**Goal**: Load historical currency rates (e.g., last 2 years) without:
- ❌ Exhausting API quotas (Frankfurter: 250/day, ExchangeRate: 1500/mo)
- ❌ Running the daily pipeline in a loop (inefficient, slow)
- ❌ Cluttering Bronze layer with duplicate data structures

**Key Constraint**: Both Frankfurter and ExchangeRate-API support **date range queries** in a single API call.

---

## Anti-Pattern: Loop-Based Backfill

### ❌ DON'T DO THIS

```yaml
# BAD: Loop over dates
- id: historical_backfill
  type: io.kestra.plugin.core.flow.ForEach
  values: ["2024-01-01", "2024-01-02", ..., "2026-01-27"]  # 730 days
  tasks:
    - id: run_daily
      type: io.kestra.plugin.core.flow.Subflow
      flowId: rates_daily
```

### Why It's Bad

1. **API Quota Explosion**:
   - 730 days × 2 APIs = **1,460 API calls**
   - Frankfurter limit: 250/day → **6 days** to complete
   - ExchangeRate limit: 1500/month → Nearly exhausted for the month

2. **Inefficient**:
   - Each call has overhead (HTTP handshake, JSON parsing)
   - No parallelization (sequential by day)

3. **Observability Noise**:
   - 730 separate pipeline executions in logs
   - Hard to track overall backfill progress

4. **Error Handling Complexity**:
   - If day 500 fails, what happens?
   - Partial failures create data gaps

---

## Recommended Approach: Batch Historical API

### API Support for Date Ranges

Both APIs support querying historical data efficiently:

#### Frankfurter (ECB)
```bash
# Single API call for entire date range
GET https://api.frankfurter.app/2024-01-01..2026-01-27?from=EUR

# Response: 730 days of rates in one JSON payload
{
  "base": "EUR",
  "start_date": "2024-01-01",
  "end_date": "2026-01-27",
  "rates": {
    "2024-01-01": {"USD": 1.1050, "GBP": 0.8650, ...},
    "2024-01-02": {"USD": 1.1055, "GBP": 0.8655, ...},
    ...
    "2026-01-27": {"USD": 1.0950, "GBP": 0.8550, ...}
  }
}
```

#### ExchangeRate-API
```bash
# Historical endpoint (requires paid plan: $9.99/mo)
GET https://v6.exchangerate-api.com/v6/{API_KEY}/history/USD/2024/01/01

# Response: Single day
# NOTE: No native range support - must batch by month
```

### ✅ RECOMMENDED: Batch Backfill Pipeline

**Strategy**:
1. **Frankfurter**: Single API call for entire range (2 years)
2. **ExchangeRate**: Monthly batches (24 API calls for 2 years)
3. **Bronze Storage**: Separate bucket path for historical vs incremental
4. **Quota Tracking**: Record batch size, not individual days

---

## Implementation

### New Kestra Flow: `rates_historical_backfill.yml`

```yaml
id: rates_historical_backfill
namespace: makerates

description: |
  Historical currency rates backfill pipeline.

  Uses date range API queries (not daily loops) to minimize API usage.
  Stores in separate Bronze partition: bronze/historical/

inputs:
  - id: start_date
    type: DATE
    required: true
    description: Start date for backfill (YYYY-MM-DD)

  - id: end_date
    type: DATE
    required: true
    description: End date for backfill (YYYY-MM-DD)

variables:
  dynamodb_endpoint: http://dynamodb:8000
  minio_endpoint: http://minio:9000
  aws_access_key_id: dummy
  aws_secret_access_key: dummy
  aws_default_region: us-east-1

tasks:
  # ===== 1. VALIDATE DATE RANGE =====
  - id: validate_range
    type: io.kestra.plugin.scripts.shell.Commands
    runner: PROCESS
    commands:
      - |
        days=$(( ($(date -d "{{ inputs.end_date }}" +%s) - $(date -d "{{ inputs.start_date }}" +%s)) / 86400 ))
        echo "Backfill range: $days days"
        if [ $days -gt 730 ]; then
          echo "ERROR: Range too large (max 2 years = 730 days)"
          exit 1
        fi

  # ===== 2. FRANKFURTER BATCH EXTRACTION =====
  - id: extract_frankfurter_historical
    type: io.kestra.plugin.docker.Run
    containerImage: makerates-ingestion-base:latest
    pullPolicy: NEVER
    networkMode: makerates-network
    env:
      AWS_ACCESS_KEY_ID: "{{ vars.aws_access_key_id }}"
      AWS_SECRET_ACCESS_KEY: "{{ vars.aws_secret_access_key }}"
      AWS_DEFAULT_REGION: "{{ vars.aws_default_region }}"
      DYNAMODB_ENDPOINT: "{{ vars.dynamodb_endpoint }}"
      MINIO_ENDPOINT: "{{ vars.minio_endpoint }}"
      START_DATE: "{{ inputs.start_date }}"
      END_DATE: "{{ inputs.end_date }}"
    commands:
      - frankfurter_historical_backfill  # New script
    timeout: PT30M  # Historical data can be large

  # ===== 3. EXCHANGERATE BATCH EXTRACTION (Optional) =====
  # Only if using paid plan with historical API
  - id: extract_exchangerate_historical
    type: io.kestra.plugin.docker.Run
    containerImage: makerates-ingestion-base:latest
    pullPolicy: NEVER
    networkMode: makerates-network
    env:
      AWS_ACCESS_KEY_ID: "{{ vars.aws_access_key_id }}"
      AWS_SECRET_ACCESS_KEY: "{{ vars.aws_secret_access_key }}"
      AWS_DEFAULT_REGION: "{{ vars.aws_default_region }}"
      DYNAMODB_ENDPOINT: "{{ vars.dynamodb_endpoint }}"
      MINIO_ENDPOINT: "{{ vars.minio_endpoint }}"
      START_DATE: "{{ inputs.start_date }}"
      END_DATE: "{{ inputs.end_date }}"
      EXCHANGERATE_API_KEY: "{{ secret('EXCHANGERATE_API_KEY') }}"
    commands:
      - exchangerate_historical_backfill  # New script
    timeout: PT30M
    allowFailure: true  # Optional source

  # ===== 4. TRANSFORM (dbt with historical partition) =====
  - id: transform_historical
    type: io.kestra.plugin.docker.Run
    containerImage: makerates-ingestion-base:latest
    pullPolicy: NEVER
    networkMode: makerates-network
    workingDir: /app/dbt_project
    env:
      MINIO_ENDPOINT: "minio:9000"
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin123
      DBT_TARGET: historical  # Use separate target
    commands:
      - bash -c "dbt run --target historical && dbt test --target historical"
    timeout: PT30M

  # ===== 5. SYNC TO DYNAMODB (Full Load) =====
  - id: sync_historical_to_dynamodb
    type: io.kestra.plugin.docker.Run
    containerImage: makerates-ingestion-base:latest
    pullPolicy: NEVER
    networkMode: makerates-network
    workingDir: /app
    env:
      AWS_ACCESS_KEY_ID: "{{ vars.aws_access_key_id }}"
      AWS_SECRET_ACCESS_KEY: "{{ vars.aws_secret_access_key }}"
      AWS_DEFAULT_REGION: "{{ vars.aws_default_region }}"
      DYNAMODB_ENDPOINT: "{{ vars.dynamodb_endpoint }}"
    commands:
      - >
        python scripts/sync_to_dynamodb_simple.py
        --endpoint {{ vars.dynamodb_endpoint }}
        --mode full
        --duckdb-path dbt_project/historical.duckdb
    timeout: PT30M
```

---

## S3 Bucket Naming Conventions

### Directory Structure

```
s3://bronze-bucket/
├── bronze/                          # Daily incremental loads
│   ├── frankfurter__rates/
│   │   ├── load_id_2026-01-27_10-30-00/
│   │   │   └── data.parquet
│   │   └── _dlt_loads/
│   └── exchangerate__rates/
│       ├── load_id_2026-01-27_10-30-00/
│       │   └── data.parquet
│       └── _dlt_loads/
│
└── bronze_historical/               # Historical backfills
    ├── frankfurter__rates/
    │   ├── backfill_2024-01-01_to_2026-01-27/
    │   │   └── data.parquet
    │   └── _dlt_loads/
    └── exchangerate__rates/
        ├── backfill_2024-01-01_to_2026-01-27/
        │   └── data.parquet
        └── _dlt_loads/

DuckDB:
├── dbt_project/silver.duckdb         # Incremental (daily)
└── dbt_project/historical.duckdb     # Historical (one-time)
```

### Rationale

1. **Separate `bronze_historical/`**:
   - Clear distinction between daily and historical data
   - Different retention policies (historical = keep forever, daily = TTL)
   - Easier to re-run backfill without affecting daily pipeline

2. **Date Range in Path**:
   - `backfill_2024-01-01_to_2026-01-27/` makes it obvious what data is inside
   - No need to query data to know the range

3. **Separate DuckDB Files**:
   - `silver.duckdb`: Hot, incremental (fast queries, smaller size)
   - `historical.duckdb`: Cold archive (large, query once to populate DynamoDB)

---

## Quota Management

### API Usage for 2-Year Backfill

| Source | Method | API Calls | Quota Impact |
|--------|--------|-----------|--------------|
| **Frankfurter** | Single range query | **1 call** | 0.4% of daily quota |
| **ExchangeRate** | Monthly batches | **24 calls** | 1.6% of monthly quota |

**Conclusion**: Backfill is quota-efficient with batch API approach.

### Tracking in DynamoDB

```python
# Record batch backfill (not individual days)
quota_manager.record_request(
    api_source="frankfurter",
    success=True,
    metadata={
        "type": "historical_backfill",
        "date_range": "2024-01-01 to 2026-01-27",
        "days_loaded": 730
    }
)
```

---

## Execution Plan

### Phase 1: Frankfurter Only (Free Tier)
```bash
# Trigger backfill via Kestra UI
Flow: rates_historical_backfill
Inputs:
  start_date: 2024-01-01
  end_date: 2026-01-27

# Result: 730 days of ECB rates in DynamoDB
# Cost: 1 API call (free tier)
# Time: ~5 minutes
```

### Phase 2: Add ExchangeRate (Paid Tier)
- Upgrade to ExchangeRate-API paid plan ($9.99/mo)
- Run backfill with both sources
- Enable consensus validation for historical data

---

## Implementation Scripts

### `src/frankfurter_historical_backfill.py`

```python
"""
Frankfurter historical backfill using date range API.
Loads into bronze_historical/ partition.
"""

import dlt
import requests
import os
from datetime import datetime

@dlt.source(name="frankfurter_historical")
def frankfurter_historical_source(start_date: str, end_date: str):
    """
    Fetch historical rates using date range query.

    Args:
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
    """

    # Frankfurter date range API
    url = f"https://api.frankfurter.app/{start_date}..{end_date}?from=EUR"

    @dlt.resource(
        name="rates",
        write_disposition="replace",  # Replace for historical (idempotent)
        primary_key="extraction_id"
    )
    def get_rates():
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        # data["rates"] is a dict: {"2024-01-01": {"USD": 1.1050, ...}, ...}
        for date_str, rates_dict in data["rates"].items():
            record = {
                "extraction_id": f"frankfurter_historical_{date_str}",
                "extraction_timestamp": datetime.now().isoformat(),
                "source": "frankfurter",
                "source_tier": "primary",
                "base_currency": data["base"],
                "rate_date": date_str,
                "rates": rates_dict,
                "backfill_metadata": {
                    "backfill_range": f"{start_date} to {end_date}",
                    "backfill_timestamp": datetime.now().isoformat()
                }
            }
            yield record

    return get_rates


def run_frankfurter_historical_pipeline():
    start_date = os.getenv("START_DATE")
    end_date = os.getenv("END_DATE")

    pipeline = dlt.pipeline(
        pipeline_name="frankfurter_historical_backfill",
        destination="filesystem",
        dataset_name="bronze_historical",  # Separate dataset
    )

    load_info = pipeline.run(
        frankfurter_historical_source(start_date, end_date),
        write_disposition="replace"
    )

    print(f"✅ Historical backfill complete: {start_date} to {end_date}")
    return load_info


if __name__ == "__main__":
    run_frankfurter_historical_pipeline()
```

---

## Testing

```bash
# Test with small range first (7 days)
just backfill-test

# Full 2-year backfill
just backfill-full

# Verify Bronze layer
docker exec makerates-minio /usr/bin/mc ls --recursive local/bronze-bucket/bronze_historical/
```

---

## Monitoring

Add observability for backfill:
```python
record_pipeline_event(
    pipeline_name="rates_historical_backfill",
    status="COMPLETED",
    execution_date=end_date,
    metrics={
        "days_loaded": 730,
        "api_calls": 1,
        "sources": ["frankfurter"]
    }
)
```

---

## Future Enhancements

1. **Incremental Backfill**:
   - Only load missing date ranges (gap detection)
   - Merge into existing historical partition

2. **Multi-Currency Pairs**:
   - Load different base currencies (USD, GBP, JPY)
   - Cross-rate calculations

3. **Data Validation**:
   - Historical anomaly detection (known events: Brexit, COVID crash)
   - Outlier flagging for manual review

---

## References

- Frankfurter API Docs: https://www.frankfurter.app/docs/
- ExchangeRate-API Historical: https://www.exchangerate-api.com/docs/historical-data-requests
- dlt Replace vs Append: https://dlthub.com/docs/general-usage/incremental-loading
