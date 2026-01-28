
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  



select
    1
from "silver"."main_gold"."mart_monthly_summary"

where not(sample_count > 0)


  
  
      
    ) dbt_internal_test