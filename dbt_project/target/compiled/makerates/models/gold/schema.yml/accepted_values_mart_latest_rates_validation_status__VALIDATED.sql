
    
    

with all_values as (

    select
        validation_status as value_field,
        count(*) as n_records

    from "silver"."main_gold"."mart_latest_rates"
    group by validation_status

)

select *
from all_values
where value_field not in (
    'VALIDATED'
)


