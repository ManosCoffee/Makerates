
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select currency_pair
from "silver"."main_gold"."mart_currency_conversions"
where currency_pair is null



  
  
      
    ) dbt_internal_test