
  
  create view "analytics"."main_staging"."stg_exchangerate__dbt_tmp" as (
    

/*
Staging model for ExchangeRate-API rates.

Reads Bronze JSONL data from dlt and unpacks the flattened rates columns
into a normalized structure suitable for consensus checking.

Source: ExchangeRate-API (free tier)
Primary Source for USD-based exchange rates
*/




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

  );
