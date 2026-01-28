
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select severity
from "silver"."main_silver"."fact_rates_validated"
where severity is null



  
  
      
    ) dbt_internal_test