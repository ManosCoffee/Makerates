{{
  config(
    materialized='view',
    tags=['staging', 'frankfurter']
  )
}}

/*
Staging model for Frankfurter (ECB) rates.

Reads Bronze JSONL data from dlt and unpacks the flattened rates columns
into a normalized structure suitable for consensus checking.

Source: Public Frankfurter API (ECB data)
Secondary Source for EUR-based exchange rates
*/

{% set metadata_path = get_latest_iceberg_metadata(get_iceberg_table_path("frankfurter_rates")) %}

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
    -- Read from Raw Iceberg Table (Compacted & Deduplicated)
    SELECT *
    FROM iceberg_scan('{{ metadata_path }}')
    WHERE source = 'frankfurter'
),

-- Extract all rates__* columns into rows using UNPIVOT
unnested_rates AS (
    UNPIVOT bronze_data
    ON COLUMNS('^rates__.*')
    INTO
        NAME target_currency
        VALUE exchange_rate
),

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
    -- Deduplicate for each rate_date based on LATEST extraction_timestamp
    SELECT * FROM ranked_rates
    WHERE rn = 1
)

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
    CURRENT_TIMESTAMP AS dbt_loaded_at
FROM deduplicated
WHERE exchange_rate > 0
ORDER BY extraction_timestamp DESC, target_currency

{% endif %}
