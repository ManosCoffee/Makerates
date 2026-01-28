
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) <10 as should_error
    from (
      
    
  



select
    1
from "silver"."main_gold"."mart_currency_conversions"

where not((SELECT COUNT(DISTINCT from_currency) FROM mart_currency_conversions) >= 10)


  
  
      
    ) dbt_internal_test