



select
    1
from "silver"."main_silver"."stg_frankfurter"

where not(exchange_rate < 1000000)

