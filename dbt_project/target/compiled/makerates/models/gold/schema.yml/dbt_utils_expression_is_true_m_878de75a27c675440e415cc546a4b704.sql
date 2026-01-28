



select
    1
from "silver"."main_gold"."mart_currency_conversions"

where not((SELECT COUNT(DISTINCT from_currency) FROM mart_currency_conversions) >= 10)

