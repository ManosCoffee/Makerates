
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select status
from "analytics"."main_validation"."consensus_check"
where status is null



  
  
      
    ) dbt_internal_test