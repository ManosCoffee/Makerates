





with validation_errors as (

    select
        month, target_currency
    from "silver"."main_gold"."mart_monthly_summary"
    group by month, target_currency
    having count(*) > 1

)

select *
from validation_errors


