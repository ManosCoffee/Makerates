



select
    1
from "silver"."main_gold"."mart_latest_rates"

where not(exchange_rate > 0)

