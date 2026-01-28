-- ============================================================================
-- Migration Script: Old Schema → Star Schema
-- ============================================================================
-- Purpose: Migrate data from old single-table SCD Type 2 schema to star schema
--
-- Prerequisites:
-- 1. Backup your database: pg_dump currency_rates > backup.sql
-- 2. Ensure star_schema.sql has been executed
-- 3. Review this script before running
--
-- WARNING: This migration is APPEND-ONLY. It does not delete old tables.
-- You can test queries on both schemas before dropping old tables.
-- ============================================================================

-- ============================================================================
-- STEP 1: Verify Prerequisites
-- ============================================================================

DO $$
BEGIN
    -- Check that old tables exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'silver_rates') THEN
        RAISE EXCEPTION 'Old schema table silver_rates not found. Nothing to migrate.';
    END IF;

    -- Check that new tables exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'fact_rates_current') THEN
        RAISE EXCEPTION 'New star schema not found. Run schema/star_schema.sql first.';
    END IF;

    RAISE NOTICE 'Prerequisites validated. Ready to migrate.';
END $$;


-- ============================================================================
-- STEP 2: Populate Dimension Tables
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 2.1: Populate dim_currency from old schema
-- ----------------------------------------------------------------------------
INSERT INTO dim_currency (currency_code, is_active)
SELECT DISTINCT base_currency, TRUE
FROM silver_rates
WHERE base_currency NOT IN (SELECT currency_code FROM dim_currency)
UNION
SELECT DISTINCT target_currency, TRUE
FROM silver_rates
WHERE target_currency NOT IN (SELECT currency_code FROM dim_currency);

RAISE NOTICE 'dim_currency populated with % currencies',
    (SELECT COUNT(*) FROM dim_currency);


-- ----------------------------------------------------------------------------
-- 2.2: Populate dim_source from old schema
-- ----------------------------------------------------------------------------
INSERT INTO dim_source (source_name, source_type, is_active)
SELECT DISTINCT
    source_name,
    CASE
        WHEN source_tier = 'primary' THEN 'primary'
        WHEN source_tier = 'fallback' THEN 'fallback'
        ELSE 'unknown'
    END,
    TRUE
FROM silver_rates
WHERE source_name NOT IN (SELECT source_name FROM dim_source);

RAISE NOTICE 'dim_source populated with % sources',
    (SELECT COUNT(*) FROM dim_source);


-- ----------------------------------------------------------------------------
-- 2.3: Ensure dim_date is populated for migration date range
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    min_date DATE;
    max_date DATE;
BEGIN
    -- Get date range from old schema
    SELECT MIN(rate_timestamp::DATE), MAX(rate_timestamp::DATE)
    INTO min_date, max_date
    FROM silver_rates;

    -- Populate dim_date for this range
    PERFORM populate_dim_date(min_date, max_date);

    RAISE NOTICE 'dim_date populated from % to %', min_date, max_date;
END $$;


-- ============================================================================
-- STEP 3: Migrate to fact_rates_current (Latest Rates Only)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 3.1: Insert latest rates (where valid_to IS NULL)
-- ----------------------------------------------------------------------------
INSERT INTO fact_rates_current (
    base_currency_key,
    target_currency_key,
    source_key,
    date_key,
    exchange_rate,
    rate_timestamp,
    previous_rate,
    rate_change_pct,
    change_reason,
    created_at,
    updated_at
)
SELECT
    bc.currency_key,
    tc.currency_key,
    ds.source_key,
    TO_CHAR(sr.rate_timestamp, 'YYYYMMDD')::INT,
    sr.exchange_rate,
    sr.rate_timestamp,
    NULL,  -- No previous rate in old schema
    NULL,  -- No change tracking in old schema
    'migration',
    sr.created_at,
    CURRENT_TIMESTAMP
FROM silver_rates sr
JOIN dim_currency bc ON sr.base_currency = bc.currency_code
JOIN dim_currency tc ON sr.target_currency = tc.currency_code
JOIN dim_source ds ON sr.source_name = ds.source_name
WHERE sr.valid_to IS NULL  -- Only current rates
ON CONFLICT (base_currency_key, target_currency_key, source_key) DO NOTHING;

RAISE NOTICE 'fact_rates_current populated with % latest rates',
    (SELECT COUNT(*) FROM fact_rates_current);


-- ============================================================================
-- STEP 4: Migrate to fact_rates_history (All Historical Rates)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 4.1: Insert all historical rates
-- ----------------------------------------------------------------------------
-- NOTE: This inserts ALL rates from old schema, not just changes.
-- This defeats the "store only changes" optimization for historical data,
-- but preserves your complete history.
--
-- If you want to apply "store only changes" retroactively, see STEP 5.
-- ----------------------------------------------------------------------------
INSERT INTO fact_rates_history (
    base_currency_key,
    target_currency_key,
    source_key,
    date_key,
    exchange_rate,
    rate_timestamp,
    previous_rate,
    rate_change_pct,
    change_reason,
    created_at
)
SELECT
    bc.currency_key,
    tc.currency_key,
    ds.source_key,
    TO_CHAR(sr.rate_timestamp, 'YYYYMMDD')::INT,
    sr.exchange_rate,
    sr.rate_timestamp,
    NULL,  -- No previous rate tracking in old schema
    NULL,  -- No change % tracking
    'migration',
    sr.created_at
FROM silver_rates sr
JOIN dim_currency bc ON sr.base_currency = bc.currency_code
JOIN dim_currency tc ON sr.target_currency = tc.currency_code
JOIN dim_source ds ON sr.source_name = ds.source_name
ORDER BY sr.rate_timestamp;  -- Important: chronological order

RAISE NOTICE 'fact_rates_history populated with % historical rates',
    (SELECT COUNT(*) FROM fact_rates_history);


-- ============================================================================
-- STEP 5: (OPTIONAL) Apply "Store Only Changes" Retroactively
-- ============================================================================
-- This step removes historical rates that didn't change significantly,
-- applying the 0.01% threshold retroactively.
--
-- WARNING: This is DESTRUCTIVE. Only run if you want to compress history.
-- ============================================================================

-- Uncomment to apply:
-- DELETE FROM fact_rates_history
-- WHERE rate_key IN (
--     SELECT h1.rate_key
--     FROM fact_rates_history h1
--     JOIN fact_rates_history h2
--         ON h1.base_currency_key = h2.base_currency_key
--         AND h1.target_currency_key = h2.target_currency_key
--         AND h1.source_key = h2.source_key
--         AND h2.rate_timestamp < h1.rate_timestamp
--     WHERE ABS(h1.exchange_rate - h2.exchange_rate) / h2.exchange_rate < 0.0001
--         AND h1.change_reason = 'migration'
-- );


-- ============================================================================
-- STEP 6: Refresh Materialized Views
-- ============================================================================

REFRESH MATERIALIZED VIEW CONCURRENTLY vw_rates_latest;
REFRESH MATERIALIZED VIEW CONCURRENTLY vw_rates_daily_agg;
REFRESH MATERIALIZED VIEW CONCURRENTLY vw_rates_monthly_agg;

RAISE NOTICE 'Materialized views refreshed';


-- ============================================================================
-- STEP 7: Validate Migration
-- ============================================================================

DO $$
DECLARE
    old_current_count INT;
    new_current_count INT;
    old_total_count INT;
    new_history_count INT;
BEGIN
    -- Count current rates in old schema
    SELECT COUNT(*) INTO old_current_count
    FROM silver_rates
    WHERE valid_to IS NULL;

    -- Count current rates in new schema
    SELECT COUNT(*) INTO new_current_count
    FROM fact_rates_current;

    -- Count total rates in old schema
    SELECT COUNT(*) INTO old_total_count
    FROM silver_rates;

    -- Count historical rates in new schema
    SELECT COUNT(*) INTO new_history_count
    FROM fact_rates_history;

    RAISE NOTICE '';
    RAISE NOTICE '======================================';
    RAISE NOTICE 'MIGRATION VALIDATION';
    RAISE NOTICE '======================================';
    RAISE NOTICE 'Old schema - Current rates: %', old_current_count;
    RAISE NOTICE 'New schema - Current rates: %', new_current_count;
    RAISE NOTICE 'Old schema - Total rates: %', old_total_count;
    RAISE NOTICE 'New schema - Historical rates: %', new_history_count;
    RAISE NOTICE '';

    -- Validate counts match
    IF old_current_count != new_current_count THEN
        RAISE WARNING 'Current rate counts do not match! Check migration.';
    ELSE
        RAISE NOTICE '✅ Current rates migrated successfully';
    END IF;

    IF old_total_count != new_history_count THEN
        RAISE WARNING 'Historical rate counts do not match! This is expected if you applied "store only changes" in STEP 5.';
    ELSE
        RAISE NOTICE '✅ Historical rates migrated successfully';
    END IF;
END $$;


-- ============================================================================
-- STEP 8: Sample Queries to Test Migration
-- ============================================================================

-- Test 1: Get latest USD to EUR rate (should match old schema)
SELECT 'Test 1: Latest USD to EUR rate' AS test;

-- Old schema
SELECT exchange_rate AS old_schema_rate
FROM silver_rates
WHERE base_currency = 'USD'
    AND target_currency = 'EUR'
    AND valid_to IS NULL
LIMIT 1;

-- New schema
SELECT exchange_rate AS new_schema_rate
FROM vw_rates_latest
WHERE base_currency = 'USD'
    AND target_currency = 'EUR'
LIMIT 1;


-- Test 2: Count historical rate changes for USD to EUR
SELECT 'Test 2: Historical rate count for USD/EUR' AS test;

-- Old schema
SELECT COUNT(*) AS old_schema_count
FROM silver_rates
WHERE base_currency = 'USD'
    AND target_currency = 'EUR';

-- New schema
SELECT COUNT(*) AS new_schema_count
FROM fact_rates_history h
JOIN dim_currency bc ON h.base_currency_key = bc.currency_key
JOIN dim_currency tc ON h.target_currency_key = tc.currency_key
WHERE bc.currency_code = 'USD'
    AND tc.currency_code = 'EUR';


-- Test 3: Daily aggregates (new capability not in old schema)
SELECT 'Test 3: Daily aggregates for January 2024' AS test;

SELECT date, avg_rate, min_rate, max_rate, sample_count
FROM vw_rates_daily_agg
WHERE base_currency = 'USD'
    AND target_currency = 'EUR'
    AND date BETWEEN '2024-01-01' AND '2024-01-31'
ORDER BY date
LIMIT 10;


-- ============================================================================
-- STEP 9: (OPTIONAL) Drop Old Tables After Validation
-- ============================================================================
-- ONLY run this after you've validated the migration and tested queries!
-- Keep old tables for at least 1 week as a safety net.
-- ============================================================================

-- Uncomment to drop old tables:
-- DROP TABLE IF EXISTS silver_rates CASCADE;
-- DROP TABLE IF EXISTS bronze_extraction CASCADE;  -- If you want to remove bronze too
-- DROP VIEW IF EXISTS gold_latest_rates CASCADE;

-- RAISE NOTICE 'Old schema tables dropped';


-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================

RAISE NOTICE '';
RAISE NOTICE '======================================';
RAISE NOTICE 'MIGRATION COMPLETE';
RAISE NOTICE '======================================';
RAISE NOTICE 'Old tables preserved for validation';
RAISE NOTICE '';
RAISE NOTICE 'Next steps:';
RAISE NOTICE '1. Test queries on new schema';
RAISE NOTICE '2. Update application to use PostgresStarLoader';
RAISE NOTICE '3. Monitor for 1 week';
RAISE NOTICE '4. Drop old tables if satisfied';
RAISE NOTICE '';
