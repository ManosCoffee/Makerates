
    
    

with all_values as (

    select
        status as value_field,
        count(*) as n_records

    from "analytics"."main_validation"."consensus_check"
    group by status

)

select *
from all_values
where value_field not in (
    'FLAGGED'
)


