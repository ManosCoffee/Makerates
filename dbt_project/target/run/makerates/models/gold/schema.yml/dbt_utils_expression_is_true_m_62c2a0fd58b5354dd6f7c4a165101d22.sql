
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  



select
    1
from "silver"."main_gold"."mart_currency_conversions"

where not(exchange_rate > 0)


  
  
      
    ) dbt_internal_test