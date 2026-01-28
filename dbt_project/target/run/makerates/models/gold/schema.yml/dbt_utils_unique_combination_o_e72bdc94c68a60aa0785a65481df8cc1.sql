
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  





with validation_errors as (

    select
        month, target_currency
    from "silver"."main_gold"."mart_monthly_summary"
    group by month, target_currency
    having count(*) > 1

)

select *
from validation_errors



  
  
      
    ) dbt_internal_test