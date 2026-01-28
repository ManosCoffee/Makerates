
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select extraction_id
from "silver"."main_silver"."fact_rates_validated"
where extraction_id is null



  
  
      
    ) dbt_internal_test