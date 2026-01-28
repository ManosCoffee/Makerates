# Critical Architecture Decisions - Answered

This document addresses 3 critical questions raised during implementation.

---

## Q1: direnv vs dotenv ✅ IMPLEMENTED

**Question:** "Substitute dotenv with direnv controlled from makefile"

**Answer:** ✅ **DONE.** direnv is superior for development workflows.

**Why direnv is better:**
- Auto-loads/unloads env vars when entering/leaving directory
- No need to `source .env` manually
- Integrates with shell (zsh, bash)
- Prevents env var leakage between projects

**Implementation:**
```bash
# Setup
make direnv-setup

# This creates .envrc from template
# Edit .envrc with your config
# Run: direnv allow

# Now env vars auto-load when you cd into project
cd /path/to/makerates  # → Auto-loads .envrc
cd ~                    # → Auto-unloads
```

**Files:**
- [.envrc](.envrc) - Your local config (gitignored)
- [.envrc.example](.envrc.example) - Template to copy
- [Makefile](Makefile) - Added `direnv-setup` and `direnv-check` targets

---

## Q2: SCD Type 2 Bloat ⚠️ Valid Concern, Premature Optimization

**Question:** "If we load data every 4h, db is going to be bloated after a while. Any smarter way?"

**Answer:** ⚠️ **It's not bloat YET, but you're right to think ahead.**

### The Math

- 6 extractions/day × 160 currencies = **960 records/day**
- 960 × 365 = **350,400 records/year**
- After 5 years: **1.75 million records**

**Is this bloat?**
- PostgreSQL handles **billions** of records
- 1.75M records = ~200MB storage (tiny)
- With proper indexing, queries are <50ms

**Verdict:** NOT bloat... but you can optimize.

---

### Optimization Strategy (Recommended)

**Phase 1 (NOW): Store Only CHANGES**
```python
# Only insert if rate changed by >0.01%
def should_insert_rate(new_rate, last_rate):
    pct_change = abs((new_rate - last_rate) / last_rate)
    return pct_change > 0.0001  # 1 basis point

# Impact: 90% reduction (960 → ~100 records/day)
```

**Why this works:**
- Most FX rates don't change significantly intraday
- USD/EUR might change 0.0001 (insignificant)
- Only store when rate moves >0.01%

**Trade-off:**
- Pro: 90% less storage, faster queries
- Con: Lose exact timestamp of checks (but have timestamp of CHANGES)

**Verdict:** ✅ **Implement this.** It's what production systems do.

---

**Phase 2 (Year 2+): Partitioning**
```sql
-- Partition by month when you hit >1M records
CREATE TABLE silver_rates_2024_01 PARTITION OF silver_rates
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
```

**Why:**
- Queries on recent data scan smaller partitions (faster)
- Can archive/drop old partitions
- PostgreSQL best practice for time-series

**When to do this:** When you hit >1 million records

---

**Phase 3 (Year 3+): Hot/Warm/Cold Storage**
```
Hot (last 90 days):  PostgreSQL  (fast, expensive)
Warm (91-365 days):  DuckDB/S3   (queryable, cheap)
Cold (>1 year):      Parquet/S3  (archive, pennies)
```

**Why:**
- 95% cost reduction (S3 is 10x cheaper)
- Still queryable via DuckDB federation
- Postgres stays fast

**When to do this:** When you have >1 year of data and want to save $$

---

### Summary Table

| Strategy | When | Impact | Complexity |
|----------|------|--------|------------|
| **Store only changes** | NOW | 90% reduction | Low (easy to implement) |
| **Partitioning** | >1M records | Faster queries | Medium |
| **Hot/Warm/Cold** | >1 year data | 95% cost savings | High |

**See full analysis:** [03-scd-type2-optimization.md](03-scd-type2-optimization.md)

---

## Q3: FastAPI "makerex" Service ⚠️ USE CASE SPECIFIC

**Question:** "How about a FastAPI 'makerex' that all internal services can grab forex data from?"

**Answer:** ⚠️ **Depends on your use case. For YOUR stated requirements, probably NO.**

### Decision Tree

```
Do you have 3+ services consuming rates?
└─ NO (just analytics + Make.com) → ❌ Don't build API

Is this customer-facing (real-time pricing)?
└─ NO (just analytics) → ❌ Don't build API

Do you need business logic (margins, rounding)?
└─ NO (just raw rates) → ❌ Don't build API

Do external partners need access?
└─ NO (internal only) → ❌ Don't build API

Conclusion: Direct PostgreSQL access is sufficient
```

---

### When You DON'T Need API (Your Current Case)

**Your stated use case:**
- Analytics team (batch queries)
- Make.com workflows (has native Postgres connector)
- Verify production source (comparison queries)

**Architecture:**
```
Analytics Dashboard → PostgreSQL ← Make.com
                           ↑
                      Pipeline
```

**Why no API:**
- Make.com has **native PostgreSQL connector** (no API needed)
- Analytics tools (Tableau, Looker) prefer **direct SQL**
- No latency from network hop
- One less service to maintain
- Simpler architecture

**Verdict:** ❌ **Don't build API.** Direct DB access is simpler and faster.

---

### When You DO Need API

**Build FastAPI "makerex" if:**

1. **Real-time customer pricing**
   - "Show prices in customer's currency on checkout"
   - Need: <50ms latency, Redis caching, 99.9% SLA

2. **3+ microservices consuming rates**
   - Order Service, Billing Service, Payment Service
   - Want: Centralized logic, single DB connection pool

3. **External partners need access**
   - Partners can't have direct DB access
   - Need: API keys, rate limiting, audit logs

4. **Business logic requirements**
   - Add margins: `rate × 1.03` (3% buffer)
   - Enforce minimum rates (regulatory)
   - Want: Single place for logic

**Then:**
```python
# FastAPI with Redis caching
@app.get("/rates/latest")
@cache(expire=300)  # 5 min cache
async def get_rate(from_curr: str, to_curr: str):
    rate = db.get_latest_rate(from_curr, to_curr)
    return {"rate": rate, "cached": True}
```

---

### Cost-Benefit Analysis

| Aspect | Direct DB | FastAPI API |
|--------|-----------|-------------|
| **Latency** | 5-10ms | 20-50ms (network hop) |
| **Caching** | App-level | Redis (centralized) |
| **Ops complexity** | Just Postgres | Postgres + API + Redis + LB |
| **Best for** | 1-2 consumers, analytics | 3+ services, customer-facing |

---

### My Recommendation

**For your assignment:**
❌ **Don't build the API.** Your use case doesn't justify it.

**Evolution path:**
1. **Now:** Direct PostgreSQL access (simplest)
2. **If 3+ services:** Add FastAPI layer
3. **If customer-facing:** Add Redis caching
4. **If external partners:** Add authentication

**Build it when you need it, not before.**

**See full analysis:** [04-api-layer-decision.md](04-api-layer-decision.md)

---

## Summary of Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| **1. direnv vs dotenv** | ✅ Use direnv | Better DX, auto-load/unload, shell integration |
| **2. SCD Type 2 bloat** | ⚠️ Not bloat yet, but optimize | Implement "store only changes" → 90% reduction |
| **3. FastAPI "makerex"** | ❌ Not for current use case | Direct DB access is simpler, Make.com has Postgres connector |

---

## Action Items

**Immediate (Do Now):**
- [x] Implement direnv (DONE)
- [ ] Implement "store only changes" logic (optional, but recommended)
- [ ] Document decision not to build API (DONE)

**Future (When Needed):**
- [ ] Add partitioning (when >1M records)
- [ ] Add hot/warm/cold storage (when >1 year data)
- [ ] Build FastAPI API (if use case changes to customer-facing or 3+ services)

---

## Questions to Answer Before Changing Direction

**Before building an API:**
1. How many services consume rates? (If <3, don't build API)
2. Is this customer-facing? (If no, probably don't build API)
3. Do you need sub-50ms latency? (If no, direct DB is fine)
4. Do external partners need access? (If no, don't build API)

**Before implementing hot/warm/cold storage:**
1. Do you have >1 year of data? (If no, wait)
2. Is PostgreSQL slow? (If no, don't optimize)
3. Is storage cost a concern? (If no, don't complicate)

**Philosophy: Build for 80% use case, document evolution path.**
