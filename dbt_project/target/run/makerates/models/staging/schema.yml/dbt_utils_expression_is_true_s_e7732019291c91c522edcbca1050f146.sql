
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  



select
    1
from "analytics"."main_staging"."stg_currencylayer"

where not(exchange_rate > 0)


  
  
      
    ) dbt_internal_test