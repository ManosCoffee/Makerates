
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select risk_level
from "silver"."main_gold"."mart_rate_volatility"
where risk_level is null



  
  
      
    ) dbt_internal_test