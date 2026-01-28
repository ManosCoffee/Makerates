
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select rate_date
from "silver"."main_silver"."stg_exchangerate"
where rate_date is null



  
  
      
    ) dbt_internal_test