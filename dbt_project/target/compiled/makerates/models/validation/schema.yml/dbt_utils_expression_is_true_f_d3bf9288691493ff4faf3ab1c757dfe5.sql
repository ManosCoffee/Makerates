



select
    1
from "analytics"."main_validation"."fact_rates_validated"

where not(exchange_rate < 1000000)

