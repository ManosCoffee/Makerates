
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select target_currency
from "silver"."main_silver"."stg_exchangerate"
where target_currency is null



  
  
      
    ) dbt_internal_test