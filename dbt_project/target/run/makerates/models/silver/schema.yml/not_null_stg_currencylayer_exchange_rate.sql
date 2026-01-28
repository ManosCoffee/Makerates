
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select exchange_rate
from "silver"."main_silver"."stg_currencylayer"
where exchange_rate is null



  
  
      
    ) dbt_internal_test