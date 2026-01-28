



select
    1
from "analytics"."main_staging"."stg_frankfurter"

where not(exchange_rate < 1000000)

