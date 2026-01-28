
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        source as value_field,
        count(*) as n_records

    from "analytics"."main_staging"."stg_currencylayer"
    group by source

)

select *
from all_values
where value_field not in (
    'currencylayer'
)



  
  
      
    ) dbt_internal_test