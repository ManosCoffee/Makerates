
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select extraction_timestamp
from "silver"."main_silver"."stg_currencylayer"
where extraction_timestamp is null



  
  
      
    ) dbt_internal_test