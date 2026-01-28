



select
    1
from "analytics"."main_staging"."stg_currencylayer"

where not(exchange_rate > 0)

