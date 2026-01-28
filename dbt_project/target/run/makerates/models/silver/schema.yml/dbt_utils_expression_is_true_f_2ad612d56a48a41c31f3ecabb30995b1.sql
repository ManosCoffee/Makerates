
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  



select
    1
from "silver"."main_silver"."fact_rates_validated"

where not((SELECT COUNT(DISTINCT target_currency) FROM fact_rates_validated WHERE rate_date = (SELECT MAX(rate_date) FROM fact_rates_validated)) >= 100)


  
  
      
    ) dbt_internal_test