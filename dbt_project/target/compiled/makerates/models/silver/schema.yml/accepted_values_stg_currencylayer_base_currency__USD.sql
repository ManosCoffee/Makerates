
    
    

with all_values as (

    select
        base_currency as value_field,
        count(*) as n_records

    from "silver"."main_silver"."stg_currencylayer"
    group by base_currency

)

select *
from all_values
where value_field not in (
    'USD'
)


