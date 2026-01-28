
    
    

with all_values as (

    select
        severity as value_field,
        count(*) as n_records

    from "analytics"."main_validation"."consensus_check"
    group by severity

)

select *
from all_values
where value_field not in (
    'WARNING','CRITICAL'
)


