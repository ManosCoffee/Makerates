
  
    
    

    create  table
      "silver"."main_silver"."stg_openexchange__dbt_tmp"
  
    as (
      

/*
Staging model for Open Exchange Rates.

Reads Bronze JSONL data from dlt and unpacks the flattened rates columns
into a normalized structure suitable for consensus checking.

Source: Open Exchange Rates API (commercial)
Base Currency: USD
*/

WITH bronze_data AS (
    -- Read from dlt's Bronze output (JSONL files on MinIO/S3)
    -- dlt flattens the nested rates object into rates__XXX columns
    SELECT *
    FROM read_json(
        's3://bronze-bucket/bronze/rates/*.jsonl.gz',
        format='newline_delimited',
        compression='gzip'
    )
    WHERE http_status_code = 200  -- Only successful API calls
      AND source = 'openexchange'  -- Filter for Open Exchange data only
),

-- Extract all rates__* columns into rows using UNPIVOT
-- Note: Column list should match what's in the data
unnested_rates AS (
    SELECT
        extraction_id,
        extraction_timestamp,
        source,
        source_tier,
        base_currency,
        rate_timestamp,
        'PLACEHOLDER' AS target_currency,
        0.0 AS exchange_rate
    FROM bronze_data
    WHERE 1=0  -- No data yet (API key required)
)

SELECT
    extraction_id,
    CAST(extraction_timestamp AS TIMESTAMP) AS extraction_timestamp,
    source,
    source_tier,
    base_currency,
    target_currency,
    CAST(exchange_rate AS DOUBLE) AS exchange_rate,
    CAST(CURRENT_DATE AS DATE) AS rate_date,
    -- Add calculated fields
    CONCAT(base_currency, '/', target_currency) AS currency_pair,
    CASE WHEN exchange_rate > 0 THEN 1.0 / exchange_rate ELSE 0.0 END AS inverse_rate,
    -- Metadata
    CURRENT_TIMESTAMP AS dbt_loaded_at
FROM unnested_rates
WHERE exchange_rate > 0
ORDER BY extraction_timestamp DESC, target_currency
    );
  
  