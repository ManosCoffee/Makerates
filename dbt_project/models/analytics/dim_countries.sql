{{
  config(
    materialized='table',
    tags=['analytics', 'dimension']
  )
}}

SELECT
    UPPER(country_code) as country_code,
    country_name,
    UPPER(currency_code) as currency_code,
    region
FROM {{ ref('country_currencies') }}
