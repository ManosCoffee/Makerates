
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  



select
    1
from "silver"."main_silver"."consensus_check"

where not(variance_pct > 0.005)


  
  
      
    ) dbt_internal_test