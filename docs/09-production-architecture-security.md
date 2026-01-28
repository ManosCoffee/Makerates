# Production Architecture: Security, Compliance, Storage

## Overview

This document addresses production concerns:
- **Security:** API key rotation, HTTPS, OAuth, rate limiting
- **Compliance:** Auditability, immutability, retention
- **Storage:** Parquet/Iceberg on MinIO vs PostgreSQL JSONB
- **Tooling:** DLT Hub for ingestion

---

## A. Security

### 1. API Key Management

**Current (Insecure):**
```python
api_key = os.getenv("EXCHANGERATE_API_KEY")  # Static, no rotation
```

**Production (Secure):**
```python
from aws_secretsmanager_caching import SecretCache

cache = SecretCache()

def get_api_key():
    """Get API key with automatic rotation"""
    secret = cache.get_secret_string("currency-pipeline/exchangerate-api")
    return json.loads(secret)['api_key']

# Rotate every 90 days via Lambda
def rotate_secret(event, context):
    # 1. Generate new key via provider API
    # 2. Update secrets manager
    # 3. Keep old key valid for 24h grace period
    pass
```

**Key rotation strategy:**
- Primary key: Active (used for all requests)
- Secondary key: Grace period (24h after rotation)
- Rotation schedule: Every 90 days
- Alert if rotation fails

---

### 2. HTTPS + Certificate Pinning

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import ssl_

class SecureHTTPAdapter(HTTPAdapter):
    """Force TLS 1.3+ with certificate verification"""

    def init_poolmanager(self, *args, **kwargs):
        context = ssl_.create_urllib3_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

session = requests.Session()
session.mount('https://', SecureHTTPAdapter())
```

---

### 3. Rate Limiting

```python
from ratelimit import limits, sleep_and_retry
from tenacity import retry, stop_after_attempt, wait_exponential

class RateLimitedExtractor:
    """API client with rate limiting and exponential backoff"""

    @sleep_and_retry
    @limits(calls=100, period=60)  # 100 calls/minute
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60)
    )
    def extract(self):
        response = self.session.get(url, timeout=30)

        # Check rate limit headers
        remaining = int(response.headers.get('X-RateLimit-Remaining', 0))
        if remaining < 10:
            logger.warning("Rate limit approaching", remaining=remaining)

        return response
```

---

### 4. User-Agent

```python
session.headers.update({
    'User-Agent': 'MakeRates/1.0 (https://makerates.example.com; ops@example.com)',
    'Accept': 'application/json',
    'Accept-Encoding': 'gzip, deflate',
})
```

**Why:** Many APIs block requests without proper User-Agent.

---

## B. Bronze Layer: Comprehensive Metadata

### Enhanced Bronze Schema

```sql
CREATE TABLE bronze_extraction (
    -- Identity
    extraction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Source tracking
    source_name VARCHAR(100) NOT NULL,
    source_version VARCHAR(50),  -- API version
    source_tier VARCHAR(50) NOT NULL,  -- primary, fallback

    -- Request metadata (CRITICAL for auditability)
    request_url TEXT NOT NULL,
    request_method VARCHAR(10) DEFAULT 'GET',
    request_headers JSONB,  -- User-Agent, API version, auth method
    request_params JSONB,
    request_body JSONB,

    -- Response metadata
    http_status_code INTEGER NOT NULL,
    response_headers JSONB,  -- Content-Type, Rate-Limit, Cache headers
    raw_response JSONB NOT NULL,  -- Immutable API response

    -- Performance tracking
    extraction_duration_ms DOUBLE PRECISION,
    response_size_bytes INTEGER,

    -- Error handling
    error_message TEXT,
    error_code VARCHAR(50),
    retry_attempt INTEGER DEFAULT 0,

    -- Compliance
    data_classification VARCHAR(50) DEFAULT 'internal',
    retention_policy VARCHAR(50) DEFAULT 'keep-5-years',

    -- Infrastructure
    extraction_host VARCHAR(255),
    extraction_user VARCHAR(100),
    pipeline_version VARCHAR(50),  -- git commit hash

    -- Immutability
    response_checksum VARCHAR(64) NOT NULL,  -- SHA256 of raw_response

    -- Lineage
    parent_extraction_id UUID,  -- If this is a re-extraction

    CONSTRAINT check_valid_status CHECK (http_status_code BETWEEN 100 AND 599)
);

CREATE INDEX idx_bronze_timestamp ON bronze_extraction(extraction_timestamp DESC);
CREATE INDEX idx_bronze_checksum ON bronze_extraction(response_checksum);
```

---

### Why All This Metadata?

#### B1. Avoiding Reprocessing Costs

**Scenario:** Transformation logic changes

```python
# Day 1: Round to 2 decimals
def transform_v1(bronze):
    rate = bronze.raw_response['conversion_rates']['EUR']
    return round(rate, 2)  # 0.92

# Day 30: "We need 4 decimals for crypto!"
# WITHOUT bronze: Re-call API for 30 days
#   Cost: 30 days × 6 calls/day × $0.01 = $1.80
#   Risk: API might not have historical data

# WITH bronze: Reprocess from storage
def reprocess_historical():
    bronze_records = get_bronze_range(last_30_days)
    for record in bronze_records:
        rate = record.raw_response['conversion_rates']['EUR']
        new_rate = round(rate, 4)  # 0.9234
        update_silver(record.extraction_id, new_rate)

# Cost: $0
# Time: Seconds
```

---

#### B2. Auditability

**Scenario:** "Why does this rate look wrong?"

```python
def audit_suspicious_rate(date, currency_pair):
    """Trace rate back to source"""

    # 1. Get processed rate from silver
    silver = get_silver_rate(date, currency_pair)
    # Shows: 0.92

    # 2. Get raw data from bronze
    bronze = get_bronze_by_id(silver.extraction_id)
    # Shows: API sent 0.9234

    # 3. Compare
    api_sent = bronze.raw_response['conversion_rates']['EUR']
    we_stored = silver.exchange_rate

    if api_sent != we_stored:
        # BUG IN OUR CODE
        print(f"Transformation error: {api_sent} → {we_stored}")

    # 4. Verify immutability
    checksum = hashlib.sha256(
        json.dumps(bronze.raw_response, sort_keys=True).encode()
    ).hexdigest()

    if checksum != bronze.response_checksum:
        # ALERT: Data tampered with
        raise SecurityError("Bronze data has been modified!")
```

**Compliance (SOX, GDPR):**
```sql
-- Audit log: Who accessed what, when
CREATE TABLE audit_log (
    audit_id UUID PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    action VARCHAR(50) NOT NULL,
    table_name VARCHAR(100),
    record_id UUID,
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    ip_address INET,
    query_text TEXT
);
```

---

#### B3. Resilience to Schema Evolution

**API changes schema:**

```json
// Old (v1)
{"base_code": "USD", "conversion_rates": {"EUR": 0.92}}

// New (v2) - added metadata
{"base_code": "USD", "conversion_rates": {"EUR": {"rate": 0.92, "source": "ECB"}}}
```

**With bronze layer:**
```python
def transform_flexible(bronze):
    """Handle both old and new schema"""
    rates = bronze.raw_response['conversion_rates']['EUR']

    # Detect schema version
    if isinstance(rates, dict):
        return rates['rate']  # v2
    else:
        return rates  # v1
```

**Without bronze:** Your pipeline breaks, historical data is unqueryable.

---

#### B4. Technical Debt of Parsing

**Without bronze:**
```python
# Extract and parse in one step
def extract():
    response = api.get()
    return {
        'base': response['base_code'],
        'rate': response['conversion_rates']['EUR']
    }
    # What if you later need 'time_last_update_utc'? TOO LATE!
```

**With bronze:**
```python
# Extract: Store everything
def extract():
    response = api.get()
    return ExtractionResult(raw_response=response)  # Complete

# Later: "We need update timestamps!"
def backfill_timestamps():
    for bronze in get_all_bronze():
        timestamp = bronze.raw_response['time_last_update_utc']
        update_silver_with_timestamp(bronze.extraction_id, timestamp)
    # No API calls needed!
```

---

## C. Storage Formats: PostgreSQL vs Parquet/Iceberg

### Option 1: PostgreSQL JSONB (Current)

```
Extract → PostgreSQL (bronze JSONB)
       → PostgreSQL (silver/gold star schema)
```

**Pros:**
- ✅ Simple (one database)
- ✅ ACID transactions
- ✅ SQL queries

**Cons:**
- ❌ Expensive ($50/month for 1.75M records)
- ❌ JSONB can be updated (not truly immutable)
- ❌ Doesn't scale past 10M records

---

### Option 2: Parquet on MinIO

```
Extract → MinIO (Parquet files)
       → DuckDB/Postgres (silver/gold)
       → DuckDB (analytics - query Parquet + Postgres)
```

**Pros:**
- ✅ **10x cheaper** ($5/month for 1.75M records)
- ✅ **Immutable** (files can't change)
- ✅ **Compression** (10x better than JSONB)
- ✅ Scales to billions

**Cons:**
- ⚠️ More complex (2 systems)
- ⚠️ No ACID across systems

**Implementation:**
```python
import pyarrow as pa
import pyarrow.parquet as pq
from minio import Minio

def store_bronze_in_parquet(extraction_result):
    """Store extraction in Parquet on MinIO"""

    # Convert to PyArrow table
    table = pa.Table.from_pydict({
        'extraction_id': [str(extraction_result.extraction_id)],
        'extraction_timestamp': [extraction_result.extraction_timestamp],
        'source_name': [extraction_result.source_name],
        'raw_response': [json.dumps(extraction_result.raw_response)],
        'response_checksum': [extraction_result.response_checksum],
    })

    # Write to Parquet
    filename = f"bronze/{extraction_result.extraction_timestamp.strftime('%Y/%m/%d')}/{extraction_result.extraction_id}.parquet"

    # Upload to MinIO
    client = Minio('minio:9000', access_key='key', secret_key='secret')

    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression='zstd')
    buffer.seek(0)

    client.put_object(
        'bronze-bucket',
        filename,
        buffer,
        length=buffer.getbuffer().nbytes
    )

# Query with DuckDB
import duckdb

conn = duckdb.connect()
conn.execute("INSTALL httpfs; LOAD httpfs;")
conn.execute("SET s3_endpoint='minio:9000';")
conn.execute("SET s3_access_key_id='key';")

# Query Parquet directly
result = conn.execute("""
    SELECT * FROM 's3://bronze-bucket/bronze/**/*.parquet'
    WHERE extraction_timestamp >= '2024-01-01'
""").fetchdf()
```

---

### Option 3: Iceberg/DeltaLake on MinIO (Best for Production)

```
Extract → Iceberg table on MinIO (ACID + time travel)
       → Iceberg (silver/gold)
       → DuckDB/Trino (analytics)
```

**Pros:**
- ✅ **ACID transactions** on object storage
- ✅ **Time travel** (query as of any timestamp)
- ✅ **Schema evolution** (add columns without rewrite)
- ✅ **Immutable** (versioned snapshots)
- ✅ **10x cheaper** than Postgres
- ✅ Scales to petabytes

**Cons:**
- ⚠️ Complex setup (needs catalog)

**Implementation:**
```python
from pyiceberg.catalog import load_catalog

# Create Iceberg catalog
catalog = load_catalog("default", **{
    "type": "rest",
    "uri": "http://iceberg-rest:8181",
    "s3.endpoint": "http://minio:9000"
})

# Create bronze table
schema = pa.schema([
    ('extraction_id', pa.string()),
    ('extraction_timestamp', pa.timestamp('us')),
    ('source_name', pa.string()),
    ('raw_response', pa.string()),  # JSON as string
    ('response_checksum', pa.string()),
])

catalog.create_table(
    "warehouse.bronze_extraction",
    schema=schema,
    partition_spec=PartitionSpec(
        PartitionField(source_id=2, field_id=1000, transform=DayTransform(), name="extraction_date")
    )
)

# Insert data
table = catalog.load_table("warehouse.bronze_extraction")
table.append(data_arrow_table)

# Time travel (query as of yesterday)
table.scan(snapshot_id=table.history()[-2].snapshot_id).to_arrow()
```

**Why Iceberg wins:**
- ✅ ACID on cheap storage
- ✅ Audit trail (time travel to any point)
- ✅ Schema evolution (API changes handled gracefully)
- ✅ Immutable (compliance requirement)

---

### Recommended Architecture

**For assignment:**
```
PostgreSQL JSONB (bronze + silver + gold)
```
Simple, sufficient for <1M rows.

---

**For production:**
```
Iceberg on MinIO (bronze - immutable, ACID, time travel)
    ↓
Iceberg (silver/gold)
    ↓
DuckDB (analytics - federation)
    ↓
PostgreSQL view (last 90 days for Make.com)
```

**Why:**
- Iceberg: Cheap, scalable, ACID, auditable
- DuckDB: Fast analytics across Iceberg + Postgres
- Postgres: Make.com connector (only recent data)

---

## D. DLT Hub Assessment

**DLT Hub** (Data Load Tool) is a Python framework for building data pipelines.

### What DLT Provides

```python
import dlt

# Define pipeline
pipeline = dlt.pipeline(
    pipeline_name="currency_rates",
    destination="postgres",
    dataset_name="currency_data"
)

# Define source
@dlt.resource
def exchangerate_api_source():
    response = requests.get(url).json()
    yield response

# Run pipeline
pipeline.run(exchangerate_api_source())
```

**What it handles:**
- ✅ Schema inference (auto-creates tables)
- ✅ Incremental loading (resume from last run)
- ✅ Data typing (JSON → SQL types)
- ✅ Error handling (retry logic)
- ✅ State management (track last extraction)
- ✅ Multiple destinations (Postgres, BigQuery, Snowflake)

---

### Should You Use DLT Hub?

**Pros:**
- ✅ Less boilerplate (auto schema, typing)
- ✅ Handles incremental loads
- ✅ Built-in retry/error handling
- ✅ Multi-destination support

**Cons:**
- ❌ **Less control** (black box for complex logic)
- ❌ **Opinionated** (dictates structure)
- ❌ **Not designed for ELT** (does transformation)
- ❌ **PostgreSQL-specific features lost** (partitioning, materialized views)

---

### Comparison

| Aspect | Custom (What We Built) | DLT Hub |
|--------|------------------------|---------|
| **Control** | ✅ Full control | ❌ Black box |
| **ELT pattern** | ✅ TRUE ELT | ⚠️ Does ETL |
| **PostgreSQL features** | ✅ Partitions, views | ❌ Limited |
| **Bronze layer** | ✅ Custom metadata | ⚠️ Auto-schema |
| **Boilerplate** | ⚠️ More code | ✅ Less code |
| **Learning curve** | ⚠️ Steeper | ✅ Easier |

---

### Recommendation

**For your assignment:** ❌ **Don't use DLT Hub**

**Why:**
- You've already built TRUE ELT (validation in transformation, not extraction)
- You have custom bronze layer metadata (audit trail, checksums)
- You use PostgreSQL-specific features (partitioning, star schema)
- DLT Hub would lose these benefits

**When to use DLT Hub:**
- ✅ Simple ETL (not ELT)
- ✅ Quick prototyping
- ✅ Standard schemas (no custom metadata)
- ✅ Multiple destinations (Postgres, BigQuery, Snowflake)

**Your current implementation is more sophisticated than DLT Hub.**

---

## Summary

### Security
- ✅ Use secrets manager (AWS/Vault) for API keys
- ✅ Rotate keys every 90 days
- ✅ Force TLS 1.3+
- ✅ Rate limiting + exponential backoff
- ✅ Proper User-Agent

### Bronze Layer
- ✅ Store comprehensive metadata (request + response + infra)
- ✅ Checksums for immutability
- ✅ Enables reprocessing without API calls
- ✅ Audit trail for compliance

### Storage
**Assignment:** PostgreSQL JSONB (simple)
**Production:** Iceberg on MinIO (cheap, ACID, scalable)

### DLT Hub
❌ **Don't use** - Your custom implementation is better for TRUE ELT

---

## Implementation Priority

**Phase 1 (Assignment):**
- ✅ PostgreSQL JSONB bronze
- ✅ Star schema silver/gold
- ✅ Basic security (HTTPS, env vars)

**Phase 2 (Production MVP):**
- ✅ Secrets manager
- ✅ Enhanced bronze metadata
- ✅ Audit logging

**Phase 3 (Scale):**
- ✅ Migrate to Iceberg on MinIO
- ✅ DuckDB for analytics
- ✅ Time travel queries
