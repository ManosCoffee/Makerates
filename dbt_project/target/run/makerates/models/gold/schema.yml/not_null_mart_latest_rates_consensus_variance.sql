
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select consensus_variance
from "silver"."main_gold"."mart_latest_rates"
where consensus_variance is null



  
  
      
    ) dbt_internal_test