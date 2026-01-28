
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  



select
    1
from "analytics"."main_validation"."fact_rates_validated"

where not(exchange_rate < 1000000)


  
  
      
    ) dbt_internal_test