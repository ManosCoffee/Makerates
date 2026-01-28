
    select
      count(*) as failures,
      count(*) <0.90 as should_warn,
      count(*) <0.80 as should_error
    from (
      
    
  



select
    1
from "silver"."main_gold"."mart_data_quality_metrics"

where not(ok_rate >= 0.90)


  
  
      
    ) dbt_internal_test