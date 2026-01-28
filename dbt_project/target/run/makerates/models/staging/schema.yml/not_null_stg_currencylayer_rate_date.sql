
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select rate_date
from "analytics"."main_staging"."stg_currencylayer"
where rate_date is null



  
  
      
    ) dbt_internal_test