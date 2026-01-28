
    select
      count(*) as failures,
      count(*) <100 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  



select
    1
from "silver"."main_gold"."mart_data_quality_metrics"

where not(currency_count >= 100)


  
  
      
    ) dbt_internal_test