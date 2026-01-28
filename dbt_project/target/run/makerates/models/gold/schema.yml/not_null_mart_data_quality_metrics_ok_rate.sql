
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select ok_rate
from "silver"."main_gold"."mart_data_quality_metrics"
where ok_rate is null



  
  
      
    ) dbt_internal_test