



select
    1
from "silver"."main_gold"."mart_currency_conversions"

where not(inverse_rate > 0)

