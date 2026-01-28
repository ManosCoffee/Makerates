
    
    

with all_values as (

    select
        severity as value_field,
        count(*) as n_records

    from "silver"."main_silver"."fact_rates_validated"
    group by severity

)

select *
from all_values
where value_field not in (
    'OK'
)


