# Business Requirements Analysis

## What We Know (From Assignment)

> "Our company plans to expand its payment options to support multiple currencies in addition to the USD we currently offer. To achieve this, our analytics team needs to source external currency rates. This source will enable us to **convert currencies, verify the production source, and provide a backup** if necessary."

### Stated Requirements
1. **Convert currencies** - Enable multi-currency support
2. **Verify production source** - Validate against external rates
3. **Provide backup** - Failover if production source fails

---

## Critical Questions We DON'T Know

### 1. Who Are the Consumers?

**Unknown:** Who will actually use this data?

**Possible answers:**
- **Analytics team** → Reporting revenue in single currency (daily batch is fine)
- **Customer-facing pricing page** → Showing prices in EUR/GBP/JPY (may not need real-time)
- **Payment processing** → Checkout calculations (might use Stripe's rates instead)
- **Finance/Treasury** → FX reconciliation and audit (daily/weekly batch)

**Impact on architecture:**
- Analytics: Batch daily, PostgreSQL storage
- Customer pricing: Depends on update frequency (see below)
- Payment: Might not need this pipeline at all (use Stripe/payment processor)
- Finance: Batch daily with audit trail (our current design)

**Current assumption:** Analytics + verification use case (NOT real-time customer pricing)

---

### 2. What's the Data Freshness SLA?

**Unknown:** How fresh must the data be?

**Possible answers:**
- **Real-time (<1 min)** → Requires streaming, expensive ($500-2000/month API costs)
- **Near real-time (5-15 min)** → Frequent batch (every 15 min), moderate cost
- **Hourly** → Standard batch processing
- **Daily** → Simplest, cheapest (ECB publishes once daily anyway)
- **Weekly/Manual** → Finance team controlled updates

**Impact on architecture:**
- Real-time: Need streaming APIs, WebSocket connections, Redis cache
- 15 min: Batch API calls, PostgreSQL likely sufficient
- Daily: Simple batch job, Airflow orchestration

**Current assumption:** 4-6 hour batch updates (based on "analytics team" mention)

---

### 3. What's the Read Pattern?

**Unknown:** How many requests will query this data?

**Possible answers:**
- **Low (<10 req/sec)** → PostgreSQL with proper indexing is plenty
- **Medium (10-100 req/sec)** → PostgreSQL with materialized views
- **High (>1000 req/sec)** → Need Redis cache layer
- **Very high (>10k req/sec)** → Need distributed cache, CDN

**Impact on architecture:**
- Low/Medium: PostgreSQL is fine (our current design)
- High: Add Redis cache for hot data (top 20 currency pairs)
- Very high: Need CDN, multi-region deployment

**Current assumption:** Low to medium read volume (analytics queries, not customer-facing API)

---

### 4. Who Controls Pricing?

**Unknown:** Are prices automatically calculated or manually set?

**Real-world SaaS patterns:**

**Option A: Manual Pricing (Most Common)**
- Finance team sets prices per region: $29/month = €28/month (NOT €26.73)
- Prices are round numbers for marketing (€9, €19, €49)
- FX rates used only for **internal analytics** (revenue reporting)
- **This pipeline serves analytics, not pricing**

**Option B: Dynamic Conversion**
- Website shows: "$29/month (€26.73/month based on today's rate)"
- Prices update daily/weekly as FX rates change
- Risk: Customer confusion ("why did price change?")
- **Less common for SaaS subscriptions**

**Option C: Buffer Margins**
- Base price: $29
- EUR price: $29 × (current_rate + 3% buffer)
- Update monthly/quarterly
- **This pipeline provides rates, Finance adds buffer**

**Make.com's actual pricing** (from their website):
- Shows both USD and EUR prices
- Prices are round numbers (€9, €29, €99)
- These are **localized tiers, not real-time conversions**

**Impact on architecture:**
- Option A: Pipeline is for analytics only (simple batch)
- Option B: Need reliable, stable rates with gradual updates
- Option C: Pipeline provides raw rates, business logic adds buffer

**Current assumption:** Option A (analytics use case) or Option C (Finance-controlled pricing)

---

### 5. What Does "Verify Production Source" Mean?

**Unknown:** What is the "production source" being verified?

**Possible interpretations:**

**Option 1: Verify Payment Processor**
- Production source = Stripe's exchange rates
- Use case: "Is Stripe charging us fair FX rates?"
- Action: Daily comparison, alert if deviation >0.5%
- **This is audit/compliance**

**Option 2: Verify Our Own Pricing**
- Production source = Prices shown on Make.com website
- Use case: "Are our EUR prices still competitive vs USD?"
- Action: Weekly review, flag if drift >5%
- **This is pricing strategy**

**Option 3: Verify Another Data Pipeline**
- Production source = Existing internal currency data
- Use case: Legacy system vs new system reconciliation
- Action: Parallel run during migration
- **This is migration validation**

**Impact on architecture:**
- Option 1: Need reconciliation module (compare Stripe API vs our rates)
- Option 2: Need pricing deviation alerts
- Option 3: Need dual-write/dual-read pattern

**Current assumption:** Option 1 (verify Stripe/payment processor rates)

---

## Recommended Next Steps (Before More Coding)

### Step 1: Stakeholder Interview (Simulate)

**Questions to ask Make.com stakeholders:**

**To Analytics Team:**
1. What reports need multi-currency data?
2. How often do these reports run? (Daily? Weekly? Monthly?)
3. What's acceptable data latency? (1 hour old? 24 hours old?)
4. Do you need historical rates for backtesting?

**To Finance Team:**
1. How do you currently set EUR/GBP prices? (Manual? Automatic?)
2. How often do you update prices? (Real-time? Monthly? Quarterly?)
3. What's your tolerance for FX rate deviation? (±0.1%? ±5%?)
4. What's the "production source" we're verifying? (Stripe? Another vendor?)

**To Product Team:**
1. Do customers see dynamically converted prices or fixed localized prices?
2. What currencies are priority? (EUR? GBP? JPY? All 161?)
3. What's the roadmap timeline? (MVP in 2 weeks? Production in 6 months?)

### Step 2: Define SLAs Based on Answers

| Metric | Conservative (Safe) | Aggressive (Risky) |
|--------|--------------------|--------------------|
| **Data Freshness** | 24 hours (daily batch) | 15 minutes (frequent batch) |
| **Availability** | 99% (some downtime OK) | 99.9% (high availability) |
| **Latency (read)** | <500ms | <50ms |
| **Coverage** | Top 10 currencies | All 161 currencies |
| **Historical Depth** | 1 year | 7 years (audit requirement) |

### Step 3: Right-Size Architecture

**If answers suggest LOW requirements** (analytics, daily updates):
- ✅ Batch every 4-24 hours
- ✅ PostgreSQL only (no Redis)
- ✅ Simple Python scripts (no Airflow for POC)
- ✅ Single region deployment

**If answers suggest HIGH requirements** (customer-facing, real-time):
- Need streaming or frequent batch (every 5-15 min)
- Need Redis cache
- Need Airflow orchestration
- Need monitoring/alerting
- Need multi-region for resilience

---

## Current Architectural Assumptions (To Validate)

| Assumption | Confidence | Risk if Wrong |
|------------|-----------|---------------|
| **Use case is analytics + audit** | Medium | High (wrong architecture) |
| **Daily batch is acceptable** | Medium | Medium (might need hourly) |
| **PostgreSQL sufficient for reads** | High | Low (easy to add Redis later) |
| **Top 30 currencies enough** | Medium | Low (can add more sources) |
| **7-year retention for audit** | Low | Medium (might be overkill) |
| **No customer-facing pricing** | Medium | High (would need different design) |

---

## What This Pipeline SHOULD Do (Best Guess)

Based on typical SaaS patterns and assignment hints:

### Primary Use Case: Analytics & Reporting
- **Who:** Analytics team, Finance team
- **What:** Convert all revenue to USD for reporting
- **When:** Daily batch (overnight ETL)
- **Why:** Executives want single-currency P&L

### Secondary Use Case: Audit & Verification
- **Who:** Finance team, Compliance
- **What:** Verify Stripe's FX rates are market-rate
- **When:** Weekly reconciliation
- **Why:** Prevent overcharging, ensure fair rates

### Tertiary Use Case: Backup Rates
- **Who:** Payment system
- **What:** If Stripe rate API fails, use our rates
- **When:** Rare failover scenario (<0.1% of time)
- **Why:** Business continuity

### NOT a Use Case (Probably):
- ❌ Real-time customer pricing updates
- ❌ FX trading / speculation
- ❌ High-frequency calculations (>1000/sec)

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-24 | Use ELT (not ETL) | Flexibility, reprocessing, audit trail |
| 2026-01-24 | Start with PostgreSQL only | Simplicity, likely sufficient for analytics |
| 2026-01-24 | Batch every 4-6 hours | Balance freshness vs API cost |
| 2026-01-24 | Skip streaming | No evidence of real-time requirement |
| 2026-01-24 | Skip Redis (for now) | Premature optimization, add if needed |
| 2026-01-24 | Skip ML predictions | Over-engineering, no business case |
| 2026-01-24 | Move validation to transform layer | True ELT pattern, more resilient |

---

## Open Questions for Code Review / Discussion

1. **Should we support historical rate queries?** (e.g., "What was EUR rate on 2025-03-15?")
2. **Do we need minute-level granularity or daily is OK?**
3. **What's the actual "production source" to verify against?**
4. **How many Make.com scenarios will read from this data?** (affects read volume)
5. **Is this for a specific product (e.g., Make.com Enterprise) or all tiers?**

---

## Conclusion

**We're building for the 80% use case:** Analytics and audit with daily batch updates.

**If requirements change** (e.g., real-time pricing), we can evolve:
- Increase batch frequency (easy)
- Add Redis cache (medium)
- Add streaming (hard, expensive)

**The current simplified architecture is appropriate for a data engineer assignment** and can scale up if needed.
