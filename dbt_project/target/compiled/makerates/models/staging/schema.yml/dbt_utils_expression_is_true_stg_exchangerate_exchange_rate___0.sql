



select
    1
from "analytics"."main_staging"."stg_exchangerate"

where not(exchange_rate > 0)

