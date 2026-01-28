# Your Questions Answered

This document answers all your questions from this session.

---

## Q1: "What should we put as final DB for analytics? What about ClickHouse? DuckDB?"

**Answer:** It depends on your requirements.

### For Your Assignment

**Use:** PostgreSQL with star schema

**Why:**
- ✅ Make.com has **native PostgreSQL connector** (critical requirement)
- ✅ Your scale is small (<1M rows/year)
- ✅ Star schema + materialized views = fast enough (<10ms queries)
- ✅ Easy to operate

### Hybrid Approach (Production at Scale)

**Use:** PostgreSQL (hot) + Parquet (cold) + DuckDB (analytics)

```
PostgreSQL (last 90 days)
  ↓ archive monthly
Parquet on S3 (>90 days)
  ↓ query with
DuckDB (federation)
```

**Benefits:**
- PostgreSQL: Make.com integration ✅
- Parquet: 95% cost reduction ✅
- DuckDB: Fast analytics across both ✅

### ClickHouse

**Use IF:**
- You have billions of rows
- You don't need Make.com connector
- You need 100x faster analytics
- You're okay with eventual consistency

**For your assignment:** ❌ **Overkill** (no Make.com connector)

**See:** [docs/07-analytics-database-comparison.md](07-analytics-database-comparison.md)

---

## Q2: "Do we need queues/Kafka?"

**Answer:** ❌ **ABSOLUTELY NOT**

### The Math

**Your throughput:**
```
Extractions per day: 6 (every 4 hours)
Records per extraction: 160
Writes per day: 960

Throughput: 960 / (24 × 3600) = 0.011 writes/sec
```

**Kafka designed for:** >1000 writes/sec

**Your pattern:** Batch (scheduled)
**Kafka designed for:** Streaming (continuous)

### Kafka Overhead

**Infrastructure cost:**
```
3 Kafka brokers: $150/month
3 Zookeeper nodes: $75/month
Monitoring: $50/month
Total: $275/month + dev time
```

**What you're sending:** 192KB/day

**You'd be paying $275/month to handle 192KB/day.**

### The Right Approach

**Use:** Simple cron job or Airflow

```bash
# Every 4 hours
0 */4 * * * python run_pipeline.py

Cost: $0
Complexity: Minimal
```

### When You Would Need Kafka

**IF requirements changed to:**
- ✅ Real-time WebSocket feed (not batch)
- ✅ >100 events/sec
- ✅ Multiple services consume same data
- ✅ Need event replay

**Then use Kafka. But for batch ETL: NO.**

---

## Q3: "Why do we need TimescaleDB?"

**Answer:** ⚠️ **You don't need it yet, but nice to have**

### What TimescaleDB Provides

1. **Automatic partitioning** (vs manual)
2. **Compression** (10x storage reduction)
3. **Continuous aggregates** (incremental view refresh)
4. **Time-series functions** (time_bucket, first, last)

### Do You Need It?

**Your current situation:**
- Data: <1M rows (<100MB)
- View refresh: <10ms
- Partitioning: Manual (we implemented this)

**Add TimescaleDB when:**
- ✅ You have >10M rows (storage costs matter)
- ✅ View refreshes take >1 minute
- ✅ You want automatic partition management

**For assignment:** ❌ **Not needed**

**For production (year 2+):** ✅ **Good upgrade path**

### Upgrade Path

```
Phase 1 (NOW): PostgreSQL + star schema + manual partitioning
Phase 2 (Year 1): PostgreSQL + TimescaleDB (if slow)
Phase 3 (Year 2+): Hybrid (Postgres + Parquet + DuckDB)
```

---

## Q4: "Why psycopg2 and not SQLAlchemy?"

**Answer:** Both work. psycopg2 is simpler, SQLAlchemy has connection pooling.

### psycopg2 (What We Implemented)

**Pros:**
- ✅ Simple, direct
- ✅ Full SQL control
- ✅ No dependencies
- ✅ Perfect for assignment

**Cons:**
- ❌ No connection pooling
- ❌ No migration framework

### SQLAlchemy Core (Alternative Provided)

**Pros:**
- ✅ Connection pooling (10 connections ready)
- ✅ Alembic migrations
- ✅ Type safety
- ✅ Still uses raw SQL for ETL

**Cons:**
- ⚠️ More complex
- ⚠️ Extra dependency

### Implementations Provided

| File | Approach | When to Use |
|------|----------|-------------|
| [postgres_star_loader.py](../src/storage/postgres_star_loader.py) | psycopg2 | Assignment, simple scripts |
| [postgres_star_loader_sqlalchemy.py](../src/storage/postgres_star_loader_sqlalchemy.py) | SQLAlchemy Core | Production with pooling |

### Initialize Database

```bash
# psycopg2 version (recommended for assignment)
make db-init-star

# SQLAlchemy Core version (production)
make db-init-star-sqlalchemy
```

**Both produce identical schemas.**

### Never Use SQLAlchemy ORM

**For data warehouse ETL:**
- ❌ ORM is for CRUD, not bulk operations
- ❌ 7x slower for bulk inserts
- ❌ Doesn't support partitioning/materialized views

**See:** [docs/PSYCOPG2-VS-SQLALCHEMY-EXAMPLES.md](PSYCOPG2-VS-SQLALCHEMY-EXAMPLES.md)

---

## Summary of Decisions

| Question | Recommendation | Why |
|----------|---------------|-----|
| **Final analytics DB?** | PostgreSQL + star schema | Make.com connector + sufficient for scale |
| **ClickHouse?** | ❌ No (for assignment) | No Make.com connector, overkill for <1M rows |
| **DuckDB?** | ✅ Yes (as analytics layer) | Perfect for querying Postgres + Parquet |
| **Kafka/queues?** | ❌ Absolutely not | 0.011 writes/sec vs Kafka's 1000+/sec |
| **TimescaleDB?** | ⚠️ Not yet | Add when >10M rows or queries slow |
| **psycopg2 vs SQLAlchemy?** | psycopg2 (assignment)<br>SQLAlchemy Core (production) | Both work, Core adds pooling |

---

## Files Created

### Documentation
- [07-analytics-database-comparison.md](07-analytics-database-comparison.md) - Full DB comparison
- [08-sqlalchemy-vs-psycopg2.md](08-sqlalchemy-vs-psycopg2.md) - Driver comparison
- [PSYCOPG2-VS-SQLALCHEMY-EXAMPLES.md](PSYCOPG2-VS-SQLALCHEMY-EXAMPLES.md) - Side-by-side code

### Implementations
- [postgres_star_loader.py](../src/storage/postgres_star_loader.py) - psycopg2 version
- [postgres_star_loader_sqlalchemy.py](../src/storage/postgres_star_loader_sqlalchemy.py) - SQLAlchemy Core version

---

## What You Should Use

### For Your Assignment

**Architecture:**
```
Airflow/Cron (every 4 hours)
  ↓
Extractor (API request)
  ↓
Transformer (validate)
  ↓
PostgreSQL (star schema + partitioning)
  ↑
Make.com (native connector)
```

**No Kafka. No TimescaleDB. Just simple batch ETL.**

**Initialize:**
```bash
make docker-up
make db-init-star
```

---

### For Production (Future)

**Phase 1:** Add TimescaleDB (if queries slow)
**Phase 2:** Add hybrid storage (Postgres + Parquet + DuckDB)
**Phase 3:** Only consider ClickHouse if you drop Make.com requirement

---

## Quick Reference

### Do I Need This?

| Tool | Your Throughput | Tool Designed For | Need It? |
|------|----------------|-------------------|----------|
| **Kafka** | 0.011 writes/sec | >1000 writes/sec | ❌ No |
| **TimescaleDB** | <1M rows | >10M rows | ⚠️ Not yet |
| **ClickHouse** | <1M rows | Billions of rows | ❌ No |
| **DuckDB** | Analytics layer | Federation/analytics | ✅ Yes (later) |
| **SQLAlchemy** | Single connection | Concurrent queries | ⚠️ Optional |

**Bottom line:** Your current architecture (scheduled batch → PostgreSQL) is exactly right.

---

## Additional Reading

1. **Why star schema?** [06-star-schema-implementation.md](06-star-schema-implementation.md)
2. **Database comparison:** [07-analytics-database-comparison.md](07-analytics-database-comparison.md)
3. **psycopg2 vs SQLAlchemy:** [PSYCOPG2-VS-SQLALCHEMY-EXAMPLES.md](PSYCOPG2-VS-SQLALCHEMY-EXAMPLES.md)
4. **Quick start:** [../STAR-SCHEMA-QUICKSTART.md](../STAR-SCHEMA-QUICKSTART.md)
