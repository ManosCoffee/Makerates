
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select inverse_rate
from "silver"."main_gold"."mart_currency_conversions"
where inverse_rate is null



  
  
      
    ) dbt_internal_test