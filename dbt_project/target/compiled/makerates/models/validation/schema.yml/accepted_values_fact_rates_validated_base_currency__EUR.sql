
    
    

with all_values as (

    select
        base_currency as value_field,
        count(*) as n_records

    from "analytics"."main_validation"."fact_rates_validated"
    group by base_currency

)

select *
from all_values
where value_field not in (
    'EUR'
)


