
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select target_currency
from "silver"."main_gold"."mart_monthly_summary"
where target_currency is null



  
  
      
    ) dbt_internal_test