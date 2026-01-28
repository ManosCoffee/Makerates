
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select to_currency
from "silver"."main_gold"."mart_currency_conversions"
where to_currency is null



  
  
      
    ) dbt_internal_test