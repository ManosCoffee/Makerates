
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select rate_date
from "analytics"."main_validation"."fact_rates_validated"
where rate_date is null



  
  
      
    ) dbt_internal_test