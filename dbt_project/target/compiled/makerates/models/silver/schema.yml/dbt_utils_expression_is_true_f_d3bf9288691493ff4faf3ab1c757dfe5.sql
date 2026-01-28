



select
    1
from "silver"."main_silver"."fact_rates_validated"

where not(exchange_rate < 1000000)

