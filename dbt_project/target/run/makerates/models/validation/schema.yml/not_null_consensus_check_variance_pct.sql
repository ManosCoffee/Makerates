
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select variance_pct
from "analytics"."main_validation"."consensus_check"
where variance_pct is null



  
  
      
    ) dbt_internal_test