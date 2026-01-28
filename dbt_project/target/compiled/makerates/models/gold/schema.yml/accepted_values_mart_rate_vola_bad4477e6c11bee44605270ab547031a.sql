
    
    

with all_values as (

    select
        risk_level as value_field,
        count(*) as n_records

    from "silver"."main_gold"."mart_rate_volatility"
    group by risk_level

)

select *
from all_values
where value_field not in (
    'STABLE','MEDIUM_RISK','HIGH_RISK'
)


