
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select source
from "analytics"."main_staging"."stg_exchangerate"
where source is null



  
  
      
    ) dbt_internal_test