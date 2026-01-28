
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        severity as value_field,
        count(*) as n_records

    from "silver"."main_gold"."mart_latest_rates"
    group by severity

)

select *
from all_values
where value_field not in (
    'OK'
)



  
  
      
    ) dbt_internal_test