# Swiss Cheese Validation Stack

## Overview

The MakeRates pipeline implements a multi-layered "Swiss Cheese" validation model. Like Swiss cheese where holes don't align, this approach ensures that data quality issues are caught by at least one validation layer even if they slip through others.

## Validation Layers

### Layer 1: Structural Validation (dlt)
**Location**: [src/frankfurter_to_bronze.py](../src/frankfurter_to_bronze.py), [src/exchangerate_to_bronze.py](../src/exchangerate_to_bronze.py)
**Technology**: dlt (Data Load Tool)

**What it catches**:
- Schema violations (missing fields, wrong data types)
- Malformed JSON responses
- HTTP errors (4xx, 5xx)
- API response structure changes

**Implementation**:
```python
@dlt.resource(
    name="rates",
    write_disposition="append",
    primary_key="extraction_id"
)
def get_rates():
    response = requests.get(url, timeout=10)
    response.raise_for_status()  # HTTP validation
    data = response.json()  # JSON parsing validation

    record = {
        "extraction_id": ...,  # Required field
        "extraction_timestamp": ...,  # Required field
        "rates": data.get("rates", {}),  # Schema enforcement
        # ...
    }
    yield record
```

**Metrics Tracked**:
- HTTP status codes
- Response sizes
- API availability
- Load success/failure

---

### Layer 2: Logical Validation (dbt tests)
**Location**: [dbt_project/models/silver/schema.yml](../dbt_project/models/silver/schema.yml)
**Technology**: dbt (Data Build Tool) - native tests + dbt_utils

**What it catches**:
- Impossible values (negative rates, zero rates, NULL values)
- Out-of-range values (rates > 1M)
- Unexpected source identifiers
- Wrong base currencies
- Missing required fields

**Implementation**:
```yaml
- name: exchange_rate
  tests:
    - not_null
    - dbt_utils.expression_is_true:
        expression: "> 0"  # Rates must be positive
    - dbt_utils.expression_is_true:
        expression: "< 1000000"  # Sanity check
```

**Tests Run**:
- `not_null` on all critical fields
- `accepted_values` for categorical columns (source, base_currency, status)
- Range checks on numeric fields
- Uniqueness constraints on primary keys

---

### Layer 3: Consensus Gate (Cross-Source Validation)
**Location**: [dbt_project/models/silver/consensus_check.sql](../dbt_project/models/silver/consensus_check.sql)
**Technology**: dbt SQL model

**What it catches**:
- Source-specific data corruption
- API bugs or anomalies
- Rate manipulation attempts
- Flash crashes or erroneous rates from single source

**Implementation**:
```sql
-- Normalize both sources to EUR base
-- Calculate variance between Frankfurter (ECB) and ExchangeRate-API
SELECT
    target_currency,
    frank_rate,
    exchangerate_rate,
    ABS(frank_rate - exchangerate_rate) / frank_rate AS variance_pct,
    CASE
        WHEN variance_pct > 0.01 THEN 'CRITICAL'  -- >1%
        WHEN variance_pct > 0.005 THEN 'WARNING'  -- >0.5%
        ELSE 'OK'
    END AS severity
FROM comparison
WHERE variance_pct > 0.005  -- Only flag anomalies
```

**Thresholds**:
- `WARNING`: >0.5% variance (flag for review)
- `CRITICAL`: >1.0% variance (immediate alert)

**Key Feature**:
Only rates that agree across BOTH sources are included in `fact_rates_validated`. If Frankfurter and ExchangeRate-API disagree significantly, the rate is EXCLUDED from production data.

---

### Layer 4: Statistical Validation (Flash Crash Detection)
**Location**: [dbt_project/models/silver/schema.yml](../dbt_project/models/silver/schema.yml)
**Technology**: dbt table-level tests

**What it catches**:
- Flash crashes (sudden large movements)
- Data freshness issues (stale rates)
- Missing currency pairs
- Volume anomalies (too few currencies)

**Implementation**:
```yaml
tests:
  # Freshness check: Rates should be updated daily
  - dbt_utils.recency:
      datepart: day
      field: rate_date
      interval: 2  # Alert if no rates within 2 days

  # Volume check: Should have consistent number of currency pairs
  - dbt_utils.expression_is_true:
      expression: "(SELECT COUNT(DISTINCT target_currency) ...) >= 100"
      config:
        severity: warn
```

**Planned Enhancements** (future):
- Day-over-day volatility checks (flag if rate changes >5% in 24h)
- Rolling average deviation (Z-score)
- Historical pattern matching

---

## Validation Flow

```
┌─────────────────────────────────────────────────────┐
│ Layer 1: Structural (dlt)                           │
│ ✓ HTTP 200                                          │
│ ✓ Valid JSON                                        │
│ ✓ Schema matches                                    │
└──────────────────┬──────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────┐
│ Layer 2: Logical (dbt tests)                        │
│ ✓ exchange_rate > 0                                 │
│ ✓ exchange_rate < 1000000                           │
│ ✓ base_currency = 'EUR' (Frankfurter)               │
│ ✓ No NULL values                                    │
└──────────────────┬──────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────┐
│ Layer 3: Consensus (cross-source)                   │
│ ✓ Frankfurter vs ExchangeRate-API                   │
│ ✓ Variance < 0.5%                                   │
│ ✓ Agreement on major pairs                          │
└──────────────────┬──────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────┐
│ Layer 4: Statistical (flash crash, freshness)       │
│ ✓ Rate updated within 2 days                        │
│ ✓ At least 100 currencies present                   │
│ ✓ No day-over-day volatility >5% (future)           │
└──────────────────┬──────────────────────────────────┘
                   │
                   ↓
            ┌──────────────┐
            │ fact_rates_  │
            │  validated   │ ← SINGLE SOURCE OF TRUTH
            └──────────────┘
                   │
                   ↓
            ┌──────────────┐
            │  DynamoDB    │ ← Hot Tier (Make.com)
            │  Gold Layer  │
            └──────────────┘
```

## Observability

### DynamoDB Data Quality Tracking
**Location**: [scripts/record_data_quality.py](../scripts/record_data_quality.py)

Tracks **DATA QUALITY METRICS** from actual API parsing and validation:
- Rows extracted per source (Frankfurter, ExchangeRate-API)
- Rows validated (passed all 4 validation layers)
- Rows flagged (consensus check anomalies)
- Currency coverage (distinct currencies)
- Anomaly severity breakdown (WARNING, CRITICAL)

**Note**: Pipeline lifecycle (start/stop/failure) is already tracked by Kestra's orchestrator. This observability focuses on the data itself.

**Access Pattern**:
```bash
# Get latest data quality metrics
just inspect-observability

# Get 7-day health summary
just health-check
```

### Metrics Recorded
Each pipeline run records:
```json
{
  "pipeline_name": "rates_daily",
  "execution_timestamp": "2026-01-27T10:30:00Z",
  "execution_date": "2026-01-27",
  "status": "DATA_QUALITY_RECORDED",
  "metrics": {
    "extraction": {
      "frankfurter_rows": 150,
      "exchangerate_rows": 150,
      "total_rows": 300
    },
    "validation": {
      "validated_rows": 150,
      "flagged_rows": 2,
      "validation_rate": "98.7%"
    },
    "coverage": {
      "currency_count": 150,
      "expected_minimum": 100
    },
    "anomalies": {
      "total_flagged": 2,
      "severity_breakdown": {
        "WARNING": 2
      }
    }
  }
}
```

### Querying Metrics
Data quality is queried from DuckDB Silver layer after dbt completes:
```sql
-- Extraction counts
SELECT COUNT(*) FROM stg_frankfurter WHERE rate_date = '2026-01-27'
SELECT COUNT(*) FROM stg_exchangerate WHERE rate_date = '2026-01-27'

-- Validated rows (passed consensus)
SELECT COUNT(*) FROM fact_rates_validated WHERE rate_date = '2026-01-27'

-- Flagged anomalies
SELECT COUNT(*) FROM consensus_check WHERE rate_date = '2026-01-27'

-- Currency coverage
SELECT COUNT(DISTINCT target_currency) FROM fact_rates_validated WHERE rate_date = '2026-01-27'
```

## Running Validation

### Manual Testing
```bash
# Run dbt with all tests
just dbt

# Run only tests (skip models)
cd dbt_project && dbt test

# Run specific test
cd dbt_project && dbt test --select stg_frankfurter
```

### Automated (Kestra)
Tests run automatically in the `transform_silver` task:
```bash
dbt run && dbt test
```

Pipeline fails if ANY test fails, preventing bad data from reaching DynamoDB.

## Trade-offs

### Strictness vs Availability
- **Current**: Fail pipeline if tests fail (strict quality gate)
- **Alternative**: Allow partial data with warnings (higher availability)
- **Decision**: Prefer strictness - better to have no data than wrong data

### Performance vs Coverage
- **Layer 2 tests**: Fast (run in seconds)
- **Layer 3 consensus**: Medium (requires JOINs across sources)
- **Layer 4 statistical**: Slow (future: historical comparisons)
- **Decision**: Run all layers on every execution (daily cadence allows thoroughness)

## Future Enhancements

1. **Layer 4 Statistical** (planned):
   - Day-over-day volatility checks
   - Z-score anomaly detection
   - Moving average bounds

2. **Alerting** (planned):
   - Slack/email notifications on CRITICAL anomalies
   - PagerDuty integration for pipeline failures
   - Dashboard for observability metrics

3. **Source Diversity** (future):
   - Add 3rd source (CurrencyAPI, Fixer.io) for stronger consensus
   - Weighted consensus (trust ECB more than commercial APIs)

## References

- dbt Testing Guide: https://docs.getdbt.com/docs/building-a-dbt-project/tests
- dbt_utils Tests: https://github.com/dbt-labs/dbt-utils
- Swiss Cheese Model (Safety Engineering): https://en.wikipedia.org/wiki/Swiss_cheese_model
