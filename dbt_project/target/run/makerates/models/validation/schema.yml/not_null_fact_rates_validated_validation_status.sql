
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select validation_status
from "analytics"."main_validation"."fact_rates_validated"
where validation_status is null



  
  
      
    ) dbt_internal_test