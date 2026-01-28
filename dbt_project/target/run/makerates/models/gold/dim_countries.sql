
  
    
    

    create  table
      "gold"."main_gold"."dim_countries__dbt_tmp"
  
    as (
      

SELECT
    UPPER(country_code) as country_code,
    country_name,
    UPPER(currency_code) as currency_code,
    region
FROM "gold"."main_gold"."country_currencies"
    );
  
  