
    
    

with all_values as (

    select
        validation_status as value_field,
        count(*) as n_records

    from "analytics"."main_validation"."fact_rates_validated"
    group by validation_status

)

select *
from all_values
where value_field not in (
    'VALIDATED'
)


