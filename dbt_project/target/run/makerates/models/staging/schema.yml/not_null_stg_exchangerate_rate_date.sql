
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select rate_date
from "analytics"."main_staging"."stg_exchangerate"
where rate_date is null



  
  
      
    ) dbt_internal_test