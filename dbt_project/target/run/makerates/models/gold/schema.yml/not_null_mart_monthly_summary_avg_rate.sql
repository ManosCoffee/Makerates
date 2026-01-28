
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select avg_rate
from "silver"."main_gold"."mart_monthly_summary"
where avg_rate is null



  
  
      
    ) dbt_internal_test