
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select base_currency
from "silver"."main_silver"."fact_rates_validated"
where base_currency is null



  
  
      
    ) dbt_internal_test