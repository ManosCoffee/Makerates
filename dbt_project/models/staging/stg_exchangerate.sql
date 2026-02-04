{{
  config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key=['base_currency', 'target_currency', 'rate_date'],
    tags=['staging', 'exchangerate']
  )
}}

{% set table_path = get_iceberg_table_path("exchangerate_rates") %}
{% set metadata_path = get_latest_iceberg_metadata(table_path, "exchangerate_rates") %}

{% if metadata_path is none %}
    -- Table doesn't exist yet, return empty result with correct schema
    SELECT
        CAST(NULL AS VARCHAR) AS extraction_id,
        CAST(NULL AS TIMESTAMP) AS extraction_timestamp,
        CAST(NULL AS VARCHAR) AS source,
        CAST(NULL AS VARCHAR) AS source_tier,
        CAST(NULL AS VARCHAR) AS base_currency,
        CAST(NULL AS VARCHAR) AS target_currency,
        CAST(NULL AS DOUBLE) AS exchange_rate,
        CAST(NULL AS DATE) AS rate_date,
        CAST(NULL AS VARCHAR) AS currency_pair,
        CAST(NULL AS DOUBLE) AS inverse_rate,
        CAST(NULL AS TIMESTAMP) AS dbt_loaded_at
    WHERE FALSE
{% else %}

WITH bronze_data AS (
    -- Read from Raw Iceberg Table
    -- Use table root path, not metadata.json path
    SELECT *
    FROM iceberg_scan('{{ table_path }}', allow_moved_paths=true)
    WHERE rate_date >= CAST('{{ env_var("EXECUTION_DATE", "1970-01-01") }}' AS DATE)

    {% if is_incremental() %}
      {% if env_var("PIPELINE_MODE", "daily") == "daily" %}
        -- Daily mode: Only process dates AFTER what we have
        AND rate_date > (SELECT MAX(rate_date) FROM {{ this }})
      {% else %}
        -- Backfill mode: Process the execution date range regardless of existing data
        -- (Allows out-of-order backfills without --full-refresh)
      {% endif %}
    {% endif %}
),

-- Extract all rates__* columns into rows using UNPIVOT
-- Using same currency list as Frankfurter for consistency
-- Extract rates map into rows using UNNEST
unnested_rates AS (
    SELECT 
        b.extraction_id,
        b.extraction_timestamp,
        b.source,
        b.source_tier,
        b.base_currency,
        b.rate_date,
        -- Unnest the map entries (turns MAP into list of structs)
        unnest(map_entries(b.rates)).key AS target_currency,
        unnest(map_entries(b.rates)).value AS exchange_rate
    FROM bronze_data b
),

-- Within-run deduplication (in case Iceberg has multiple rows for same date)
ranked_rates AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY base_currency, target_currency, rate_date
            ORDER BY extraction_timestamp DESC
        ) as rn
    FROM unnested_rates
),

deduplicated AS (
    SELECT * FROM ranked_rates WHERE rn = 1
)

-- Merge strategy: maintains uniqueness on (base_currency, target_currency, rate_date)
-- Updates existing rows, inserts new rows (upsert behavior)
SELECT
    extraction_id,
    CAST(extraction_timestamp AS TIMESTAMP) AS extraction_timestamp,
    source,
    source_tier,
    base_currency,
    UPPER(REPLACE(target_currency, 'rates__', '')) AS target_currency,
    CAST(exchange_rate AS DOUBLE) AS exchange_rate,
    CAST(rate_date AS DATE) AS rate_date,
    CONCAT(base_currency, '/', UPPER(REPLACE(target_currency, 'rates__', ''))) AS currency_pair,
    1.0 / exchange_rate AS inverse_rate,  -- For reverse calculations
    CAST(CURRENT_TIMESTAMP AS TIMESTAMPTZ) AS dbt_loaded_at
FROM deduplicated
WHERE exchange_rate > 0

{% endif %}
