
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) >2 as should_error
    from (
      
    
  



select
    1
from "silver"."main_gold"."mart_data_quality_metrics"

where not(days_since_rate <= 2)


  
  
      
    ) dbt_internal_test