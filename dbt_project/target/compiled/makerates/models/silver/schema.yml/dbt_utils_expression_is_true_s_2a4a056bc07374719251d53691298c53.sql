



select
    1
from "silver"."main_silver"."stg_currencylayer"

where not(exchange_rate < 1000000)

