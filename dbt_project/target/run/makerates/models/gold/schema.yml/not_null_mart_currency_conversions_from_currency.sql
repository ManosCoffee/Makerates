
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select from_currency
from "silver"."main_gold"."mart_currency_conversions"
where from_currency is null



  
  
      
    ) dbt_internal_test