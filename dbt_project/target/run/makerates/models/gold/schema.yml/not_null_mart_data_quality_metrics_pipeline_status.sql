
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select pipeline_status
from "silver"."main_gold"."mart_data_quality_metrics"
where pipeline_status is null



  
  
      
    ) dbt_internal_test