
    
    

with all_values as (

    select
        source as value_field,
        count(*) as n_records

    from "silver"."main_silver"."stg_frankfurter"
    group by source

)

select *
from all_values
where value_field not in (
    'frankfurter'
)


