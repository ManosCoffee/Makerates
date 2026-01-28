





with validation_errors as (

    select
        base_currency, target_currency, rate_date
    from "silver"."main_silver"."stg_exchangerate"
    group by base_currency, target_currency, rate_date
    having count(*) > 1

)

select *
from validation_errors


