
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  



select
    1
from "silver"."main_silver"."stg_exchangerate"

where not(exchange_rate < 1000000000)


  
  
      
    ) dbt_internal_test